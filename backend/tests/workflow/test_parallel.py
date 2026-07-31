"""Tests for parallel step execution (B.1-B.4)."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.workflow.parallel import (
    DEFAULT_PROVIDER_LIMIT,
    MAX_PARALLEL,
    concurrency_slot,
    gather_with_limit,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_sems():
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.mark.asyncio
async def test_concurrency_slot_acquires_and_releases():
    """A single slot can be acquired + released; counter goes back to MAX."""
    # Acquire all slots
    sems = [asyncio.Semaphore(MAX_PARALLEL) for _ in range(MAX_PARALLEL)]
    # Use the global semaphore
    from app.workflow.parallel import _get_global_sem

    g = _get_global_sem()
    initial_value = g._value  # type: ignore[attr-defined]

    async with concurrency_slot():
        assert g._value == initial_value - 1  # type: ignore[attr-defined]
    assert g._value == initial_value  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_gather_with_limit_caps_concurrency():
    """gather_with_limit must respect the per-call limit."""
    in_flight = 0
    max_in_flight = 0

    async def track(coro_id: int):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return coro_id

    coros = [track(i) for i in range(10)]
    results = await gather_with_limit(coros, limit=3)
    assert len(results) == 10
    assert max_in_flight == 3  # never more than 3 concurrent


@pytest.mark.asyncio
async def test_gather_with_limit_empty():
    results = await gather_with_limit([])
    assert results == []


@pytest.mark.asyncio
async def test_gather_with_limit_returns_exceptions():
    """return_exceptions=True ensures one failure doesn't kill siblings."""

    async def ok():
        return 1

    async def bad():
        raise ValueError("boom")

    results = await gather_with_limit([ok(), bad(), ok()], limit=2)
    # First and third are results; second is the exception
    assert results[0] == 1
    assert isinstance(results[1], ValueError)
    assert results[2] == 1


@pytest.mark.asyncio
async def test_concurrency_slot_provider_separate_limits():
    """Different providers get separate semaphores."""
    import os

    os.environ["APEXAI_PROVIDER_LIMIT_OPENAI"] = "2"
    os.environ["APEXAI_PROVIDER_LIMIT_ANTHROPIC"] = "4"
    reset_for_tests()

    from app.workflow.parallel import _get_provider_sem

    s_openai = _get_provider_sem("openai")
    s_anthropic = _get_provider_sem("anthropic")
    assert s_openai._value == 2  # type: ignore[attr-defined]
    assert s_anthropic._value == 4  # type: ignore[attr-defined]


def test_default_provider_limit_value():
    """Guard against accidental tweaks to the default."""
    assert DEFAULT_PROVIDER_LIMIT == 3


def test_max_parallel_default():
    """Default cap is 5 (matches ApexAITeam proven value)."""
    # Note: env var may override; reset first
    import os

    saved = os.environ.pop("APEXAI_WORKFLOW_MAX_PARALLEL", None)
    try:
        # Reimport to get fresh default
        import importlib

        import app.workflow.parallel as p
        importlib.reload(p)
        assert p.MAX_PARALLEL == 5
    finally:
        if saved:
            os.environ["APEXAI_WORKFLOW_MAX_PARALLEL"] = saved


@pytest.mark.asyncio
async def test_concurrent_runs_scale_correctly():
    """A burst of 20 coroutines completes in roughly ceil(20/limit) waves."""
    limit = 5
    n = 20
    sleep_per = 0.02

    async def work():
        await asyncio.sleep(sleep_per)
        return 1

    start = time.perf_counter()
    results = await gather_with_limit([work() for _ in range(n)], limit=limit)
    elapsed = time.perf_counter() - start

    assert len(results) == n
    # 20 tasks / 5 limit = 4 waves * 0.02s = ~0.08s minimum
    assert elapsed >= 4 * sleep_per * 0.9
    # Should not take wildly longer than 4 waves
    assert elapsed < 4 * sleep_per * 3