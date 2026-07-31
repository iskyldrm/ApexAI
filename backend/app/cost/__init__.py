"""Sub-System D — Cost optimization.

Three-tier LLM routing:
- Tier 1: cheap models (Ollama local / gpt-4o-mini / claude-haiku)
- Tier 2: mid-tier models (gpt-4o / claude-sonnet)
- Tier 3: expensive models (gpt-4-turbo / claude-opus)

A composite router picks the cheapest tier that can handle a given prompt:
heuristic (free) → semantic (free) → LLM fallback (gpt-4o-mini).

Daily + per-run budgets enforced via :mod:`app.cost.budget`.
"""
from app.cost.tiers import (
    MODEL_TIERS,
    Tier,
    TierConfig,
    get_model_for_tier,
)

__all__ = [
    "MODEL_TIERS",
    "Tier",
    "TierConfig",
    "get_model_for_tier",
]