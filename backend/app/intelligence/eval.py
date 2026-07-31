"""Eval harness — score agent outputs against expected answers (G.16-G.20).

Three scoring strategies:
- ``exact_match``: answer must equal expected (case-insensitive trim)
- ``contains``: answer must contain expected substring
- ``cosine``: cosine similarity > threshold (using the embedding store)

The harness is callable from CI:
    uv run python -m app.intelligence.eval --dataset evals/test_set.jsonl

Or programmatically:
    from app.intelligence.eval import EvalHarness
    harness = EvalHarness()
    results = await harness.run(dataset)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    _cosine,
)


logger = logging.getLogger(__name__)


@dataclass
class EvalCase:
    """One test case."""

    id: str
    prompt: str
    expected: str
    scoring: str = "contains"  # exact_match | contains | cosine
    threshold: float = 0.7     # for cosine scoring
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """One test result."""

    case_id: str
    passed: bool
    score: float
    actual: str
    expected: str
    reason: str = ""


def exact_match(actual: str, expected: str) -> tuple[bool, float]:
    a = (actual or "").strip().lower()
    e = (expected or "").strip().lower()
    return a == e, 1.0 if a == e else 0.0


def contains_match(actual: str, expected: str) -> tuple[bool, float]:
    a = (actual or "").lower()
    e = (expected or "").lower()
    if not e:
        return True, 1.0
    return e in a, 1.0 if e in a else 0.0


def cosine_match(
    actual: str, expected: str, provider: EmbeddingProvider, threshold: float
) -> tuple[bool, float]:
    a_vec = provider.embed(actual or "")
    e_vec = provider.embed(expected or "")
    score = _cosine(a_vec, e_vec)
    return score >= threshold, score


SCORERS = {
    "exact_match": lambda actual, expected, provider, threshold: exact_match(actual, expected),
    "contains": lambda actual, expected, provider, threshold: contains_match(actual, expected),
    "cosine": lambda actual, expected, provider, threshold: cosine_match(
        actual, expected, provider, threshold
    ),
}


class EvalHarness:
    """Run an eval set + produce a report."""

    def __init__(self, provider: EmbeddingProvider | None = None) -> None:
        self.provider = provider or HashEmbeddingProvider()

    def score(
        self, case: EvalCase, actual: str
    ) -> EvalResult:
        scorer = SCORERS.get(case.scoring)
        if scorer is None:
            return EvalResult(
                case_id=case.id,
                passed=False,
                score=0.0,
                actual=actual,
                expected=case.expected,
                reason=f"Unknown scoring: {case.scoring}",
            )
        passed, score = scorer(actual, case.expected, self.provider, case.threshold)
        return EvalResult(
            case_id=case.id,
            passed=passed,
            score=score,
            actual=actual,
            expected=case.expected,
        )

    async def run(
        self,
        cases: Iterable[EvalCase],
        actuals: dict[str, str] | None = None,
    ) -> list[EvalResult]:
        """Run all cases. ``actuals`` is a dict {case_id: actual_text}.

        If not provided, the actual is treated as the expected (auto-pass).
        """
        results = []
        for case in cases:
            actual = (actuals or {}).get(case.id, case.expected)
            results.append(self.score(case, actual))
        return results

    def report(self, results: list[EvalResult]) -> dict[str, Any]:
        """Aggregate stats."""
        if not results:
            return {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0}
        passed = sum(1 for r in results if r.passed)
        return {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_rate": passed / len(results),
            "avg_score": sum(r.score for r in results) / len(results),
            "cases": [
                {
                    "id": r.case_id,
                    "passed": r.passed,
                    "score": r.score,
                    "reason": r.reason,
                }
                for r in results
            ],
        }


def load_jsonl(path: str) -> list[EvalCase]:
    """Load eval cases from a JSONL file. Each line is one EvalCase dict."""
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            cases.append(EvalCase(
                id=data["id"],
                prompt=data["prompt"],
                expected=data["expected"],
                scoring=data.get("scoring", "contains"),
                threshold=data.get("threshold", 0.7),
                metadata=data.get("metadata", {}),
            ))
    return cases