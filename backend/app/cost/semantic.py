"""Semantic tier router — sentence-transformers + centroid similarity.

Uses cosine similarity between the prompt embedding and per-tier
centroids built from a small labeled eval set. ~1MB model, batch-friendly.

If sentence-transformers isn't installed (or no internet), falls back
to a hash-based stub so tests + dev environments don't break.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

from app.cost.tiers import Tier


@dataclass
class SemanticResult:
    """Result of a semantic tier assessment."""

    tier: Tier
    confidence: float
    signals: dict = field(default_factory=dict)
    reason: str = ""


# Labeled eval set — small but representative. Each entry: prompt + tier.
# In production, expand to 50+ entries and re-compute centroids on deploy.
# Each tuple is (sample_prompt, tier).
EVAL_SET: dict[Tier, list[str]] = {
    Tier.CHEAP: [
        "Translate 'hello' to Spanish.",
        "What's 2+2?",
        "Summarize this paragraph in one sentence.",
        "Format this JSON nicely.",
        "Spell the word 'necessary'.",
        "Convert this list to uppercase.",
        "Define the word 'ephemeral'.",
        "What's the capital of France?",
        "Trim whitespace from this string.",
        "Tell me the date today.",
    ],
    Tier.STANDARD: [
        "Implement a REST API endpoint for creating users.",
        "Write a Python function that reverses a string.",
        "Debug this failing test case.",
        "Refactor this component to use hooks.",
        "Explain how async/await works in JavaScript.",
        "Add error handling to this function.",
        "Update the README with installation steps.",
        "Test this module with pytest.",
        "Modify the config to use Redis.",
        "Run the test suite and report failures.",
    ],
    Tier.PREMIUM: [
        "Design a distributed rate limiter for 10K req/s.",
        "Analyze this codebase for security vulnerabilities.",
        "Refactor the entire authentication system.",
        "Multi-step plan to migrate from MySQL to Postgres.",
        "Architecture review of our event-driven pipeline.",
        "Trade-offs between Lambda and ECS for this workload.",
        "Postmortem of last week's outage.",
        "Prove this algorithm terminates in O(n log n).",
        "Root cause analysis of memory leak in production.",
        "Design a consensus protocol for our cluster.",
    ],
}


class _Embedder:
    """Lazy wrapper around sentence-transformers with hash-based fallback."""

    def __init__(self) -> None:
        self._model = None
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                import sentence_transformers  # noqa: F401

                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            # all-MiniLM-L6-v2 is ~80MB; downloads on first run
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def embed(self, text: str) -> list[float]:
        if self.is_available():
            try:
                model = self._load()
                vec = model.encode(text, normalize_embeddings=True)
                return [float(x) for x in vec]
            except Exception:
                pass
        # Hash-based stub: 32-dim bag-of-words-ish vector from token hashes
        return _hash_embed(text, dim=32)


def _hash_embed(text: str, dim: int = 32) -> list[float]:
    """Deterministic fallback embedding.

    Not semantically meaningful — but stable enough that same text maps
    to same vector. Lets tests run without sentence-transformers.
    """
    vec = [0.0] * dim
    for token in text.lower().split():
        h = hashlib.sha256(token.encode()).digest()
        # Use 4 bytes per dimension
        for i in range(dim):
            vec[i] += (h[i % len(h)] / 255.0) - 0.5
    # Normalize
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity — assumes vectors are normalized."""
    return sum(x * y for x, y in zip(a, b))


class SemanticRouter:
    """Embeds the prompt, compares to per-tier centroids."""

    _centroids: dict[Tier, list[float]] | None = None
    _embedder: _Embedder | None = None

    def __init__(self) -> None:
        if self._centroids is None:
            self._centroids = self._compute_centroids()
        if self._embedder is None:
            self._embedder = _Embedder()

    @classmethod
    def _compute_centroids(cls) -> dict[Tier, list[float]]:
        """Average embeddings of EVAL_SET entries per tier."""
        embedder = cls._embedder() if cls._embedder else _Embedder()
        centroids: dict[Tier, list[float]] = {}
        for tier, prompts in EVAL_SET.items():
            vecs = [embedder.embed(p) for p in prompts]
            dim = len(vecs[0])
            centroid = [0.0] * dim
            for v in vecs:
                for i, x in enumerate(v):
                    centroid[i] += x
            n = len(vecs)
            centroid = [x / n for x in centroid]
            # Normalize
            norm = math.sqrt(sum(x * x for x in centroid)) or 1.0
            centroids[tier] = [x / norm for x in centroid]
        return centroids

    def score(self, prompt: str) -> SemanticResult:
        """Return tier + similarity score."""
        if self._centroids is None:
            self._centroids = self._compute_centroids()
        assert self._embedder is not None
        prompt_vec = self._embedder.embed(prompt)

        similarities = {
            tier: _cosine(prompt_vec, centroid)
            for tier, centroid in (self._centroids or {}).items()
        }
        # Pick the tier with highest similarity
        best_tier = max(similarities, key=lambda t: similarities[t])
        best_score = similarities[best_tier]

        # Confidence: gap between best and second-best
        sorted_scores = sorted(similarities.values(), reverse=True)
        gap = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else 0
        # Map to 0..1; gap of 0.1 → confident
        confidence = min(1.0, gap / 0.1) * 0.9 + 0.1 * max(0.0, best_score)

        return SemanticResult(
            tier=best_tier,
            confidence=float(confidence),
            signals={
                "similarities": {int(t): float(s) for t, s in similarities.items()},
                "best_score": float(best_score),
            },
            reason=f"semantic match → tier {int(best_tier)} (score {best_score:.3f})",
        )