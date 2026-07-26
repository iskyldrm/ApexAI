"""Background cleanup — marks stuck agent_runs as 'stuck'.

A run is considered stuck if:
- status = 'running'
- started_at < now() - 1 hour

The cleanup function is called on FastAPI startup (as a background
asyncio task) and also exposed as POST /agent/admin/cleanup for ops.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun


logger = logging.getLogger(__name__)


STUCK_THRESHOLD = timedelta(hours=1)


async def mark_stuck_runs(session: AsyncSession) -> int:
    """Mark any 'running' agent_runs older than STUCK_THRESHOLD as 'stuck'.

    Returns the number of rows updated.
    """
    threshold = datetime.now(timezone.utc) - STUCK_THRESHOLD
    result = await session.execute(
        select(AgentRun).where(
            AgentRun.status == "running",
            AgentRun.started_at < threshold,
        )
    )
    runs = result.scalars().all()
    for run in runs:
        run.status = "stuck"
        run.error = "Marked stuck by cleanup (running > 1 hour)"
        run.finished_at = datetime.now(timezone.utc)
        logger.warning("Marked run %s as stuck", run.id)
    if runs:
        await session.commit()
    return len(runs)


async def cleanup_task(stop_event: asyncio.Event, session_factory) -> None:
    """Background loop — runs mark_stuck_runs every 5 minutes.

    Pass an ``asyncio.Event`` and a session factory callable; setting the
    event stops the task.
    """
    while not stop_event.is_set():
        try:
            async with session_factory() as session:
                count = await mark_stuck_runs(session)
                if count:
                    logger.info("Cleanup marked %d stuck runs", count)
        except Exception:
            logger.exception("cleanup_task failed")
        # Wait 5 minutes (or until stop)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass
