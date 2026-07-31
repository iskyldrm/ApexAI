"""Background worker loop — claims ready steps and runs them.

Each FastAPI process starts one worker on startup. The worker:
1. Polls the queue every 1 second (configurable)
2. Claims up to 5 steps via SELECT FOR UPDATE SKIP LOCKED
3. Dispatches each step to StepExecutor in a background asyncio task
4. Sleeps + repeats

Exits gracefully on asyncio.Event.set().
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.db import async_session_maker
from app.workflow.executor import StepExecutor
from app.workflow.parallel import MAX_PARALLEL, concurrency_slot
from app.workflow.queue import claim_ready_steps


logger = logging.getLogger(__name__)


WorkerSetup = Callable[[], tuple[object, object]]  # returns (llm_client, executor)


async def worker_loop(
    stop_event: asyncio.Event,
    llm_client_factory: Callable[[], object],
    poll_interval: float = 1.0,
    batch_size: int | None = None,
) -> None:
    """Continuously claim and execute steps until ``stop_event`` is set.

    Honors ``MAX_PARALLEL`` via the ``concurrency_slot`` context manager
    so a single worker process can't exceed the cap. Multi-replica
    deployments get the same cap per replica, with claim_ready_steps
    ensuring steps aren't double-executed.
    """
    if batch_size is None:
        batch_size = MAX_PARALLEL
    logger.info(
        "Workflow worker loop starting (poll=%.1fs batch=%d max_parallel=%d)",
        poll_interval, batch_size, MAX_PARALLEL,
    )
    while not stop_event.is_set():
        try:
            llm = llm_client_factory()
            executor = StepExecutor(llm)
            async with async_session_maker() as session:
                claimed = await claim_ready_steps(session, limit=batch_size)
            for step in claimed:
                # Each step gets its own session (commit boundaries)
                # + respects the global concurrency cap
                async def run_one(s=step) -> None:
                    async with concurrency_slot(provider=getattr(s, "provider", "")):
                        async with async_session_maker() as sess:
                            try:
                                await executor.execute(sess, s)
                            except Exception:
                                logger.exception("Step execution crashed")

                asyncio.create_task(run_one())
        except Exception:
            logger.exception("Worker loop iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass
    logger.info("Workflow worker loop stopped")
