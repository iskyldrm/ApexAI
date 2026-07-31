"""Composite tier router — heuristic → semantic → LLM fallback.

Cost-aware: heuristic is free, semantic is free (after model load),
LLM fallback costs ~$0.0001 per call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.cost.heuristic import HeuristicRouter
from app.cost.llm_router import LLMRouter
from app.cost.semantic import SemanticRouter
from app.cost.tiers import Tier, get_model_for_tier


logger = logging.getLogger(__name__)


# Confidence thresholds (per plan)
_HEURISTIC_CONFIDENCE_THRESHOLD = 0.8
_SEMANTIC_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class TierDecision:
    """Final routing decision for one prompt."""

    tier: Tier
    decided_by: str          # "heuristic" | "semantic" | "llm" | "manual" | "default"
    model: str
    confidence: float
    signals: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_log_dict(self) -> dict:
        """Stable dict for persistence in routing_decisions table."""
        return {
            "tier": int(self.tier),
            "decided_by": self.decided_by,
            "model": self.model,
            "confidence": self.confidence,
            "signals": self.signals,
            "reason": self.reason,
        }


class CompositeRouter:
    """Composes heuristic + semantic + LLM routers with confidence gating."""

    def __init__(
        self,
        heuristic: HeuristicRouter | None = None,
        semantic: SemanticRouter | None = None,
        llm_router: LLMRouter | None = None,
    ) -> None:
        self.heuristic = heuristic or HeuristicRouter()
        self.semantic = semantic or SemanticRouter()
        self.llm_router = llm_router or LLMRouter()

    async def tier_for(
        self,
        prompt: str,
        *,
        tier_override: Tier | None = None,
        context: dict | None = None,
    ) -> TierDecision:
        """Return the cheapest viable tier for ``prompt``.

        - ``tier_override`` (if set) wins everything (operator control).
        - Otherwise: heuristic → semantic → LLM fallback.
        """
        if tier_override is not None:
            return TierDecision(
                tier=tier_override,
                decided_by="manual",
                model=get_model_for_tier(tier_override),
                confidence=1.0,
                reason="operator override",
            )

        # Tier 1: heuristic (free, microseconds)
        h = self.heuristic.score(prompt)
        if h.confidence >= _HEURISTIC_CONFIDENCE_THRESHOLD:
            return TierDecision(
                tier=h.tier,
                decided_by="heuristic",
                model=get_model_for_tier(h.tier),
                confidence=h.confidence,
                signals=h.signals,
                reason=h.reason,
            )

        # Tier 2: semantic (free after model load)
        s = self.semantic.score(prompt)
        if s.confidence >= _SEMANTIC_CONFIDENCE_THRESHOLD:
            return TierDecision(
                tier=s.tier,
                decided_by="semantic",
                model=get_model_for_tier(s.tier),
                confidence=s.confidence,
                signals={**h.signals, **{"semantic": s.signals}},
                reason=s.reason,
            )

        # Tier 3: LLM fallback (costs a small model call)
        l = await self.llm_router.score(prompt)
        return TierDecision(
            tier=l.tier,
            decided_by="llm" if l.reason.startswith("llm classifier") else "manual_fallback",
            model=get_model_for_tier(l.tier),
            confidence=l.confidence,
            signals={**h.signals, "semantic": s.signals, "llm": l.signals},
            reason=l.reason,
        )

    async def decide_and_route(
        self,
        prompt: str,
        *,
        tier_override: Tier | None = None,
    ) -> tuple[TierDecision, str]:
        """Convenience: return both the decision and the model string to use."""
        decision = await self.tier_for(prompt, tier_override=tier_override)
        return decision, decision.model