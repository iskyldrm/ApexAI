"""Process queue — Postgres SKIP LOCKED + exponential backoff + DLQ.

The queue lives in the ``process_steps`` table itself. A step is "ready
to run" when:
- ``status = 'pending'`` (or 'retrying' for a re-attempt)
- ``next_retry_at IS NULL OR next_retry_at <= now()``
- all upstream steps are 'completed'

Workers claim ready steps via ``SELECT ... FOR UPDATE SKIP LOCKED``.
This is the same proven pattern ApexAITeam used on MongoDB — ported
to Postgres.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.process import ProcessDLQ, ProcessStep


logger = logging.getLogger(__name__)


# Backoff schedule (seconds): 1, 4, 16, 64, 256
BACKOFF_SECONDS: list[int] = [1, 4, 16, 64, 256]


def next_retry_delay(attempt: int) -> int:
    """Return delay (in seconds) before the next retry, given the
    attempt number that just failed (1-indexed).
    """
    if attempt <= 0:
        return 0
    idx = min(attempt - 1, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[idx]


async def claim_ready_steps(
    session: AsyncSession,
    limit: int = 5,
) -> list[ProcessStep]:
    """Atomically claim up to ``limit`` runnable steps.

    Uses ``SELECT FOR UPDATE SKIP LOCKED`` so multiple workers can call
    this concurrently without conflict. Each claimed step is set to
    ``status='running'`` and ``attempt += 1`` before being returned.
    """
    # Postgres TIMESTAMP (without tz) is naive; compare both as naive
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Find ready step IDs (without locking yet)
    candidates_q = (
        select(ProcessStep.id)
        .where(
            ProcessStep.status.in_(("pending", "retrying")),
            or_(
                ProcessStep.next_retry_at.is_(None),
                ProcessStep.next_retry_at <= now,
            ),
        )
        .order_by(ProcessStep.created_at)
        .limit(limit * 3)  # overselect; filter on readiness below
    )
    candidate_ids = [r for r in (await session.execute(candidates_q)).scalars()]

    claimed: list[ProcessStep] = []
    for step_id in candidate_ids:
        # Lock + recheck readiness (in case another worker just took it)
        step = (
            await session.execute(
                select(ProcessStep)
                .where(ProcessStep.id == step_id)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if step is None:
            continue
        if step.status not in ("pending", "retrying"):
            continue
        if step.next_retry_at and step.next_retry_at > now:
            continue

        # Mark as running + bump attempt
        step.status = "running"
        step.attempt += 1
        step.started_at = now
        step.next_retry_at = None
        claimed.append(step)

        if len(claimed) >= limit:
            break

    if claimed:
        await session.commit()
        for s in claimed:
            await session.refresh(s)
    return claimed


async def enqueue_step(
    session: AsyncSession,
    step: ProcessStep,
) -> None:
    """Mark a fresh step as ready to run (status='pending', no retry time)."""
    step.status = "pending"
    step.next_retry_at = None
    await session.commit()


async def mark_step_completed(
    session: AsyncSession,
    step: ProcessStep,
    outputs: dict,
) -> None:
    """Mark a step as successfully completed and store its outputs."""
    step.status = "completed"
    step.outputs = outputs
    step.finished_at = datetime.now(timezone.utc)
    step.error = None
    await session.commit()


async def mark_step_failed(
    session: AsyncSession,
    step: ProcessStep,
    error: str,
) -> ProcessStep | ProcessDLQ:
    """Mark a step as failed and either schedule a retry or move to DLQ.

    Returns the ProcessStep (if retrying) or the ProcessDLQ row (if exhausted).
    """
    step.error = error
    step.finished_at = datetime.now(timezone.utc)

    if step.attempt >= step.max_attempts:
        # Move to DLQ
        step.status = "failed"
        dlq = ProcessDLQ(
            process_id=step.process_id,
            step_id=step.id,
            payload={"inputs": step.inputs, "outputs": step.outputs},
            reason=error,
            retry_count=step.attempt,
        )
        session.add(dlq)
        await session.commit()
        return dlq

    # Schedule retry
    step.status = "retrying"
    step.next_retry_at = (
        datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(seconds=next_retry_delay(step.attempt))
    )
    await session.commit()
    return step


async def has_unfinished_upstreams(
    session: AsyncSession, process_id: UUID, step_name: str, definition: dict
) -> bool:
    """True if any upstream step in the DAG is not yet completed."""
    from app.workflow.definition import ProcessDefinition

    pdef = ProcessDefinition.model_validate(definition)
    upstream_names = pdef.upstream(step_name)
    if not upstream_names:
        return False
    # Check if any upstream step is not 'completed' or 'skipped'
    result = await session.execute(
        select(ProcessStep.status)
        .where(
            ProcessStep.process_id == process_id,
            ProcessStep.step_name.in_(upstream_names),
        )
    )
    statuses = {row for row in result.scalars()}
    return any(s not in ("completed", "skipped") for s in statuses)
