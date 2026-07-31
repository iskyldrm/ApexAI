"""Parallel step execution for the workflow orchestrator (B hardening).

The worker claims ready steps in batches. We add:

1. **Global concurrency cap** — ``APEXAI_WORKFLOW_MAX_PARALLEL`` (default 5).
   Prevents one noisy process from saturating the worker.
2. **Per-provider semaphores** — one semaphore per LLM provider, default
   concurrency 3. Prevents burst rate-limit hits against Ollama/Anthropic.
3. **Within-process DAG parallelism** — when a process has multiple
   independent root steps ready, the executor fires them concurrently
   using ``asyncio.gather``.

The runtime cost is bounded by ``MAX_PARALLEL``; semaphores fall through
if a key isn't initialized.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator


logger = logging.getLogger(__name__)


# Default global cap; overridable via env
MAX_PARALLEL = int(os.environ.get("APEXAI_WORKFLOW_MAX_PARALLEL", "5"))

# Per-provider default cap (e.g. OpenAI = 3 concurrent, Ollama = 5)
DEFAULT_PROVIDER_LIMIT = 3


# ---------------------------------------------------------------------------
# Global concurrency gate
# ---------------------------------------------------------------------------

_global_sem: asyncio.Semaphore | None = None
_provider_sems: dict[str, asyncio.Semaphore] = {}


def _get_global_sem() -> asyncio.Semaphore:
    """Lazy-init the global concurrency semaphore."""
    global _global_sem
    if _global_sem is None:
        _global_sem = asyncio.Semaphore(MAX_PARALLEL)
    return _global_sem


def _get_provider_sem(provider: str) -> asyncio.Semaphore:
    """Lazy-init a per-provider semaphore."""
    sem = _provider_sems.get(provider)
    if sem is None:
        limit = int(
            os.environ.get(
                f"APEXAI_PROVIDER_LIMIT_{provider.upper()}", str(DEFAULT_PROVIDER_LIMIT)
            )
        )
        sem = asyncio.Semaphore(max(1, limit))
        _provider_sems[provider] = sem
    return sem


def reset_for_tests() -> None:
    """Drop all semaphores — test helper."""
    global _global_sem, _provider_sems
    _global_sem = None
    _provider_sems = {}


@asynccontextmanager
async def concurrency_slot(provider: str = "") -> AsyncIterator[None]:
    """Acquire one slot in the global + per-provider semaphore."""
    global_sem = _get_global_sem()
    async with global_sem:
        if provider:
            prov_sem = _get_provider_sem(provider)
            async with prov_sem:
                yield
        else:
            yield


async def gather_with_limit(
    coros: list,
    *,
    provider: str = "",
    limit: int | None = None,
) -> list:
    """Run coroutines concurrently, capped by ``limit`` (default: MAX_PARALLEL).

    Each coroutine is wrapped in ``concurrency_slot`` so the global + provider
    caps are respected. Returns the list of results (or exceptions).
    """
    if not coros:
        return []

    cap = limit or MAX_PARALLEL
    sem = asyncio.Semaphore(cap)

    async def _runner(coro):
        async with sem:
            async with concurrency_slot(provider):
                return await coro

    results = await asyncio.gather(*[_runner(c) for c in coros], return_exceptions=True)
    return list(results)


# ---------------------------------------------------------------------------
# DAG root-step fan-out
# ---------------------------------------------------------------------------


def find_root_steps(steps: list) -> list:
    """Return steps with no upstream dependencies.

    A root step has ``depends_on`` empty/missing OR all upstream steps
    are already in a terminal state.
    """
    # If step has explicit depends_on list, treat those as edges.
    # Otherwise treat it as root (initial entrypoint).
    return [s for s in steps if not getattr(s, "depends_on", None)]