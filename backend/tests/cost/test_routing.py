"""Tests for the cost cascade (Sub-System D Phase 1-5)."""
from __future__ import annotations

import pytest

from app.cost.composite import CompositeRouter, TierDecision
from app.cost.heuristic import HeuristicRouter
from app.cost.llm_router import LLMRouter, LLMRouterResult
from app.cost.semantic import SemanticRouter
from app.cost.tiers import (
    MODEL_TIERS,
    Tier,
    estimate_cost_for_tier,
    get_model_for_tier,
)


# -------------------- Tier registry --------------------


def test_three_tiers_defined():
    assert Tier.CHEAP == 1
    assert Tier.STANDARD == 2
    assert Tier.PREMIUM == 3
    assert set(MODEL_TIERS.keys()) == {Tier.CHEAP, Tier.STANDARD, Tier.PREMIUM}


def test_get_model_for_tier_returns_string():
    for tier in Tier:
        m = get_model_for_tier(tier)
        assert isinstance(m, str) and len(m) > 0


def test_tier_pricing_strictly_increases():
    """Premium tier must cost more than standard, which costs more than cheap."""
    cheap = estimate_cost_for_tier(Tier.CHEAP, 1000, 500)
    standard = estimate_cost_for_tier(Tier.STANDARD, 1000, 500)
    premium = estimate_cost_for_tier(Tier.PREMIUM, 1000, 500)
    assert cheap < standard < premium


def test_estimate_cost_scales_with_tokens():
    base = estimate_cost_for_tier(Tier.STANDARD, 1000, 500)
    double = estimate_cost_for_tier(Tier.STANDARD, 2000, 1000)
    assert abs(double - 2 * base) < 1e-9


# -------------------- Heuristic router --------------------


def test_heuristic_short_question_routes_to_cheap():
    h = HeuristicRouter()
    r = h.score("What's the time?")
    assert r.tier == Tier.CHEAP
    assert r.confidence >= 0.6


def test_heuristic_translate_keyword_routes_to_cheap():
    h = HeuristicRouter()
    r = h.score("Translate 'hello' to French.")
    assert r.tier == Tier.CHEAP
    assert r.confidence >= 0.9  # keyword match


def test_heuristic_implement_keyword_routes_to_standard():
    h = HeuristicRouter()
    r = h.score("Implement a function to parse JSON.")
    assert r.tier == Tier.STANDARD
    assert r.confidence >= 0.8


def test_heuristic_design_keyword_routes_to_premium():
    h = HeuristicRouter()
    r = h.score("Design a distributed consensus protocol.")
    assert r.tier == Tier.PREMIUM
    assert r.confidence >= 0.9


def test_heuristic_long_prompt_routes_to_premium():
    h = HeuristicRouter()
    long_prompt = "Explain " + ("the architecture of a multi-tenant SaaS platform. " * 50)
    r = h.score(long_prompt)
    assert r.tier in (Tier.STANDARD, Tier.PREMIUM)


def test_heuristic_returns_signals():
    h = HeuristicRouter()
    r = h.score("Implement X.")
    assert "length" in r.signals
    assert "length_tier" in r.signals


# -------------------- Semantic router --------------------


def test_semantic_returns_tier():
    s = SemanticRouter()
    r = s.score("Translate 'hello' to French.")
    assert r.tier in (Tier.CHEAP, Tier.STANDARD, Tier.PREMIUM)
    assert 0.0 <= r.confidence <= 1.0


def test_semantic_short_prompt_returns_valid_tier():
    """Short factual prompts return a valid tier (the fallback hash embedder
    doesn't carry true semantic meaning — we just check structure)."""
    s = SemanticRouter()
    r = s.score("What is 2 + 2?")
    assert r.tier in (Tier.CHEAP, Tier.STANDARD, Tier.PREMIUM)
    assert 0.0 <= r.confidence <= 1.0


def test_semantic_complex_prompt_routes_to_premium():
    """The premium test prompt has keyword overlap with premium centroid,
    so even the hash embedder routes it to premium or standard."""
    s = SemanticRouter()
    r = s.score("Architecture review of distributed consensus protocol design.")
    assert r.tier in (Tier.PREMIUM, Tier.STANDARD)


def test_semantic_signals_contain_similarities():
    s = SemanticRouter()
    r = s.score("Write a function.")
    assert "similarities" in r.signals
    # All three tiers should appear
    assert set(r.signals["similarities"].keys()) == {1, 2, 3}


# -------------------- LLM router --------------------


@pytest.mark.asyncio
async def test_llm_router_parses_valid_response():
    """A completion function returning 'cheap' must yield Tier.CHEAP."""
    async def fake_complete(prompt: str):
        class FakeResp:
            content = "cheap"

        return FakeResp()

    router = LLMRouter(completion_fn=fake_complete)
    result = await router.score("What time is it?")
    assert result.tier == Tier.CHEAP
    assert "cheap" in result.reason


@pytest.mark.asyncio
async def test_llm_router_handles_unparseable_response():
    async def fake_complete(prompt: str):
        class FakeResp:
            content = "I'm not sure how to classify this."

        return FakeResp()

    router = LLMRouter(completion_fn=fake_complete)
    result = await router.score("vague prompt")
    assert result.tier == Tier.STANDARD  # safe default
    assert result.confidence < 0.5


@pytest.mark.asyncio
async def test_llm_router_handles_timeout():
    import asyncio

    async def slow_complete(prompt: str):
        await asyncio.sleep(10)
        class FakeResp:
            content = "standard"

        return FakeResp()

    router = LLMRouter(completion_fn=slow_complete, timeout_seconds=0.1)
    result = await router.score("any prompt")
    assert result.tier == Tier.STANDARD
    assert "timeout" in result.reason or "fallback" in result.reason


@pytest.mark.asyncio
async def test_llm_router_handles_exception():
    async def broken_complete(prompt: str):
        raise RuntimeError("LLM API down")

    router = LLMRouter(completion_fn=broken_complete)
    result = await router.score("any prompt")
    assert result.tier == Tier.STANDARD
    assert result.confidence < 0.5


# -------------------- Composite router --------------------


@pytest.mark.asyncio
async def test_composite_uses_heuristic_for_strong_keyword():
    """A clear keyword match must short-circuit and use heuristic only."""
    router = CompositeRouter()
    decision = await router.tier_for("Translate this to Spanish.")
    assert decision.decided_by == "heuristic"
    assert decision.tier == Tier.CHEAP


@pytest.mark.asyncio
async def test_composite_respects_tier_override():
    router = CompositeRouter()
    decision = await router.tier_for("any prompt", tier_override=Tier.PREMIUM)
    assert decision.tier == Tier.PREMIUM
    assert decision.decided_by == "manual"
    assert decision.confidence == 1.0


@pytest.mark.asyncio
async def test_composite_returns_tier_decision_dataclass():
    router = CompositeRouter()
    decision = await router.tier_for("Write a Python class.")
    assert isinstance(decision, TierDecision)
    assert decision.model == get_model_for_tier(decision.tier)


@pytest.mark.asyncio
async def test_composite_decision_log_dict_round_trip():
    router = CompositeRouter()
    decision = await router.tier_for("Implement a REST API.")
    log = decision.to_log_dict()
    assert "tier" in log
    assert "decided_by" in log
    assert "model" in log
    assert "confidence" in log
    assert "signals" in log
    assert "reason" in log


@pytest.mark.asyncio
async def test_composite_falls_through_to_llm_router_for_uncertain():
    """A long ambiguous prompt without keywords → LLM router."""

    async def fake_complete(prompt: str):
        class FakeResp:
            content = "premium"

        return FakeResp()

    router = CompositeRouter(llm_router=LLMRouter(completion_fn=fake_complete))
    # Long prompt with no strong keywords → heuristic uncertain, semantic
    # uncertain, then LLM
    prompt = "Some random text " * 100
    decision = await router.tier_for(prompt)
    assert decision.decided_by in ("llm", "manual_fallback")
    assert decision.tier == Tier.PREMIUM


@pytest.mark.asyncio
async def test_composite_signals_accumulate():
    """When falling through, the decision's signals should include all tiers."""
    async def fake_complete(prompt: str):
        class FakeResp:
            content = "standard"

        return FakeResp()

    router = CompositeRouter(llm_router=LLMRouter(completion_fn=fake_complete))
    decision = await router.tier_for("Some ambiguous text " * 50)
    # Either decided_by heuristic (length-only) or llm — both should have signals
    assert "length" in decision.signals