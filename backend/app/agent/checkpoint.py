"""Failure recovery + resume for agent runs.

When an agent process crashes mid-loop (OOM, k8s eviction, network blip),
the ``agent_runs`` row stays in ``running`` status and the conversation
messages up to the crash are persisted. Without intervention the run
appears stuck forever.

This module provides:

1. ``save_checkpoint(agent_run_id, step, state)`` — periodic snapshots so
   we can resume without re-running LLM calls.
2. ``load_latest_checkpoint(agent_run_id)`` — fetch the most recent
   checkpoint for resume.
3. ``mark_stuck_runs_interrupted(threshold_seconds)`` — on startup, find
   runs that have been ``running`` longer than the threshold and mark
   them ``interrupted`` (resumable).
4. ``resume_run(agent_run_id)`` — load checkpoint + conversation, then
   continue the loop from where it left off.

Used by:
- ``runtime.AgentLoop`` — saves a checkpoint every N steps.
- ``main.lifespan`` — calls ``mark_stuck_runs_interrupted`` on startup.
- ``api/routes`` — exposes ``POST /agent/runs/{id}/resume``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_run import AgentRun
from app.models.agent_run_checkpoint import AgentRunCheckpoint


logger = logging.getLogger(__name__)


# How often the loop saves a checkpoint (in steps)
CHECKPOINT_EVERY_N_STEPS = 5


async def save_checkpoint(
    session: AsyncSession,
    *,
    agent_run_id: UUID,
    step: int,
    state: dict[str, Any],
    last_message_id: UUID | None = None,
) -> AgentRunCheckpoint:
    """Persist a checkpoint for ``agent_run_id``.

    The ``state`` dict typically contains:
    - ``input_tokens`` / ``output_tokens`` — accumulated budget
    - ``intentional_files`` — list of files written
    - ``finish_reason`` — partial finish if loop exited
    """
    checkpoint = AgentRunCheckpoint(
        agent_run_id=agent_run_id,
        step=step,
        state=state,
        last_message_id=last_message_id,
    )
    session.add(checkpoint)
    await session.flush()
    return checkpoint


async def load_latest_checkpoint(
    session: AsyncSession,
    agent_run_id: UUID,
) -> AgentRunCheckpoint | None:
    """Return the most recent checkpoint for ``agent_run_id``, or None."""
    stmt = (
        select(AgentRunCheckpoint)
        .where(AgentRunCheckpoint.agent_run_id == agent_run_id)
        .order_by(AgentRunCheckpoint.step.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def mark_stuck_runs_interrupted(
    session: AsyncSession,
    *,
    threshold_seconds: int = 3600,
) -> int:
    """Mark runs older than ``threshold_seconds`` with status='running' as 'interrupted'.

    Returns the number of rows updated.
    """
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=threshold_seconds)
    stmt = select(AgentRun).where(
        AgentRun.status == "running",
        AgentRun.started_at < cutoff,
    )
    result = await session.execute(stmt)
    runs = result.scalars().all()
    for run in runs:
        run.status = "interrupted"
        run.error = (
            f"Marked interrupted after >{threshold_seconds}s with no progress "
            f"(possible worker crash). Use POST /agent/runs/{run.id}/resume to retry."
        )
        run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if runs:
        await session.commit()
        logger.warning("Marked %d stuck agent_runs as 'interrupted'", len(runs))
    return len(runs)


async def list_resumable_runs(session: AsyncSession, org_id: str | None = None) -> list[AgentRun]:
    """List runs that can be resumed (status='interrupted' or 'awaiting_approval')."""
    stmt = select(AgentRun).where(
        AgentRun.status.in_(["interrupted", "awaiting_approval"])
    )
    if org_id is not None:
        stmt = stmt.where(AgentRun.org_id == org_id)
    stmt = stmt.order_by(AgentRun.started_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_run_with_checkpoint(
    session: AsyncSession,
    agent_run_id: UUID,
) -> tuple[AgentRun, AgentRunCheckpoint | None]:
    """Convenience: load both run and latest checkpoint in one call."""
    run = await session.get(AgentRun, agent_run_id)
    if run is None:
        raise ValueError(f"AgentRun {agent_run_id} not found")
    checkpoint = await load_latest_checkpoint(session, agent_run_id)
    return run, checkpoint