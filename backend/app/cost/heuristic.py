"""Heuristic tier router — fastest, free, lowest precision.

Uses prompt length + keyword scan to pick a tier. Designed to be the
first decision point; only defers to semantic / LLM when confidence
is low.

Confidence scoring:
- Length-only signal: confidence = 0.6 (medium)
- Length + keyword match (clear tier implication): confidence = 0.95
- Conflicting signals: confidence = 0.3 (uncertain → defer)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.cost.tiers import Tier


@dataclass
class HeuristicResult:
    """Result of a heuristic tier assessment."""

    tier: Tier
    confidence: float
    signals: dict = field(default_factory=dict)
    reason: str = ""


# Keyword patterns that strongly imply a tier.
# Tier 1 (cheap) — trivial lookups, formatting, simple summaries
_TIER1_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(translate|format|uppercase|lowercase|trim|summarize in one|short summary|list the|tell me the)\b", re.I),
    re.compile(r"\b(what is|define|spell|how do you say)\b", re.I),
    re.compile(r"^\s*[\w\s]{0,40}\?\s*$", re.I),  # short question
)

# Tier 3 (premium) — deep reasoning, design, multi-file refactors
_TIER3_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(design|architect|review.*(code|architecture)|refactor.*(system|architecture)|multi-?step plan)\b", re.I),
    re.compile(r"\b(analyze.*(security|performance|correctness)|prove|theorem)\b", re.I),
    re.compile(r"\b(root cause|postmortem|trade-?offs?)\b", re.I),
)

# Tier 2 (standard) — most agent work
_TIER2_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(implement|write|edit|debug|test|run|fix|modify|update)\b", re.I),
    re.compile(r"\b(explain|describe|how does|why does)\b", re.I),
)


def _length_signal(prompt: str) -> tuple[Tier, float]:
    """Map prompt length to a tier guess + confidence.

    Very short → Tier 1; very long → Tier 3; medium → Tier 2.
    """
    n = len(prompt)
    if n < 80:
        return Tier.CHEAP, 0.6
    if n < 600:
        return Tier.STANDARD, 0.6
    if n < 2000:
        return Tier.STANDARD, 0.7
    # Long prompts need context-aware reasoning — lean premium
    return Tier.PREMIUM, 0.7


def _keyword_signal(prompt: str) -> tuple[Tier | None, float]:
    """If a strong keyword match exists, return its tier + high confidence."""
    p = prompt.lower()
    if any(p.search(prompt) for p in _TIER1_PATTERNS):
        return Tier.CHEAP, 0.95
    if any(p.search(prompt) for p in _TIER3_PATTERNS):
        return Tier.PREMIUM, 0.95
    if any(p.search(prompt) for p in _TIER2_PATTERNS):
        return Tier.STANDARD, 0.85
    return None, 0.0


class HeuristicRouter:
    """Length + keyword based tier router. No API calls — microseconds."""

    def score(self, prompt: str) -> HeuristicResult:
        """Return a tier guess with confidence + the signals we used."""
        length_tier, length_conf = _length_signal(prompt)
        keyword_tier, keyword_conf = _keyword_signal(prompt)

        signals = {
            "length": len(prompt),
            "length_tier": int(length_tier),
            "keyword_tier": int(keyword_tier) if keyword_tier else None,
        }

        # If keyword signal is strong, prefer it
        if keyword_tier is not None:
            return HeuristicResult(
                tier=keyword_tier,
                confidence=keyword_conf,
                signals=signals,
                reason=f"keyword match → tier {int(keyword_tier)}",
            )

        # No keyword signal — fall back to length with low confidence
        # so semantic / LLM router gets a chance to upgrade
        return HeuristicResult(
            tier=length_tier,
            confidence=length_conf,
            signals=signals,
            reason=f"length-only → tier {int(length_tier)}",
        )