"""Model tier registry — Tier 1 (cheap) → Tier 3 (premium).

ApexAI ships a 3-tier model registry. The composite router picks the
cheapest viable tier per prompt; operators can override per-call.

Pricing is approximate USD per 1M tokens (input + output averaged).
Override via env var APEXAI_TIER1_MODEL etc., or by editing this table.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import IntEnum


class Tier(IntEnum):
    """Model cost tiers — higher = more capable, more expensive."""

    CHEAP = 1       # sub-cent per call — local / haiku
    STANDARD = 2    # cents per call — sonnet / gpt-4o
    PREMIUM = 3     # dollars per call — opus / gpt-4-turbo


@dataclass(frozen=True)
class TierConfig:
    """One model in the registry."""

    model: str                  # litellm model string (may include provider prefix)
    provider: str               # "ollama" | "anthropic" | "openai" | ""
    input_price_per_million: float
    output_price_per_million: float
    max_input_tokens: int
    notes: str = ""


# Default tier table. Overridable via env: APEXAI_TIER{N}_MODEL.
# Note: env overrides only the model name, not the price — pricing is
# approximate and updated manually.
MODEL_TIERS: dict[Tier, TierConfig] = {
    Tier.CHEAP: TierConfig(
        model=os.environ.get("APEXAI_TIER1_MODEL", "gpt-4o-mini"),
        provider="",
        input_price_per_million=0.15,
        output_price_per_million=0.60,
        max_input_tokens=128_000,
        notes="Sub-cent per call. Use for trivial lookups, formatting, summaries.",
    ),
    Tier.STANDARD: TierConfig(
        model=os.environ.get("APEXAI_TIER2_MODEL", "gpt-4o"),
        provider="",
        input_price_per_million=2.50,
        output_price_per_million=10.00,
        max_input_tokens=128_000,
        notes="Default for general agent tasks. Good cost/quality balance.",
    ),
    Tier.PREMIUM: TierConfig(
        model=os.environ.get("APEXAI_TIER3_MODEL", "claude-sonnet-4-5"),
        provider="",
        input_price_per_million=15.00,
        output_price_per_million=75.00,
        max_input_tokens=200_000,
        notes="Expensive but high-quality. Reserved for complex reasoning.",
    ),
}


def get_model_for_tier(tier: Tier) -> str:
    """Return the model string for a tier."""
    return MODEL_TIERS[tier].model


def get_tier_config(tier: Tier) -> TierConfig:
    """Return the full config for a tier."""
    return MODEL_TIERS[tier]


def estimate_cost_for_tier(
    tier: Tier, input_tokens: int, output_tokens: int
) -> float:
    """Estimate USD cost for a call at a given tier."""
    cfg = MODEL_TIERS[tier]
    in_cost = (input_tokens / 1_000_000) * cfg.input_price_per_million
    out_cost = (output_tokens / 1_000_000) * cfg.output_price_per_million
    return in_cost + out_cost


def all_models() -> list[str]:
    """List all model names — useful for admin UIs."""
    return [cfg.model for cfg in MODEL_TIERS.values()]