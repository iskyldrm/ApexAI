"""Queue tests — SKIP LOCKED + backoff + DLQ."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import async_session_maker
from app.models.process import Process, ProcessDLQ, ProcessStep
from app.workflow.queue import (
    BACKOFF_SECONDS,
    claim_ready_steps,
    enqueue_step,
    mark_step_completed,
    mark_step_failed,
    next_retry_delay,
)


# -------------------- Unit tests --------------------


def test_next_retry_delay_uses_backoff_schedule():
    assert next_retry_delay(1) == BACKOFF_SECONDS[0]
    assert next_retry_delay(2) == BACKOFF_SECONDS[1]
    assert next_retry_delay(5) == BACKOFF_SECONDS[-1]
    # Over the schedule length → caps at last value
    assert next_retry_delay(10) == BACKOFF_SECONDS[-1]
    # attempt=0 → no delay
    assert next_retry_delay(0) == 0


# -------------------- Integration tests (DB) --------------------


async def _make_process() -> tuple[UUID, list[str]]:
    """Create a process with 3 sequential steps."""
    async with async_session_maker() as session:
        p = Process(
            name=f"test-{uuid.uuid4().hex[:6]}",
            definition={
                "name": "test",
                "steps": [
                    {"name": "a", "role": "ANL", "prompt": "p"},
                    {"name": "b", "role": "DEV_BE", "prompt": "p"},
                    {"name": "c", "role": "QA", "prompt": "p"},
                ],
                "edges": [
                    {"from": "a", "to": "b"},
                    {"from": "b", "to": "c"},
                ],
            },
            status="running",
            org_id=str(uuid.uuid4()),
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        steps = []
        for name in ("a", "b", "c"):
            s = ProcessStep(
                process_id=p.id,
                step_name=name,
                role="ANL",
                status="pending",
                prompt_template="p",
            )
            session.add(s)
            steps.append(s)
        await session.commit()
        for s in steps:
            await session.refresh(s)
        return p.id, [str(s.id) for s in steps]


@pytest.mark.asyncio
async def test_enqueue_step_makes_it_ready():
    process_id, _ = await _make_process()
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProcessStep).where(
                ProcessStep.process_id == process_id,
                ProcessStep.step_name == "a",
            )
        )
        step = result.scalar_one()
        step.status = "completed"
        await session.commit()

    async with async_session_maker() as session:
        step = await session.get(ProcessStep, step.id)
        await enqueue_step(session, step)
        await session.refresh(step)
        assert step.status == "pending"
        assert step.next_retry_at is None


@pytest.mark.asyncio
async def test_claim_ready_steps_claims_roots_first():
    process_id, _ = await _make_process()

    async with async_session_maker() as session:
        claimed = await claim_ready_steps(session, limit=10)
        names = {s.step_name for s in claimed}
        # The DAG root 'a' must be in the claimed set
        assert "a" in names
        # All claimed are running
        for s in claimed:
            assert s.status == "running"
            assert s.attempt >= 1


@pytest.mark.asyncio
async def test_claim_skips_steps_with_future_retry_time():
    process_id, _ = await _make_process()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    async with async_session_maker() as session:
        # Push a's next_retry_at to the future and mark as retrying
        result = await session.execute(
            select(ProcessStep).where(
                ProcessStep.process_id == process_id,
                ProcessStep.step_name == "a",
            )
        )
        step_a = result.scalar_one()
        step_a.status = "retrying"
        step_a.next_retry_at = future
        await session.commit()

    async with async_session_maker() as session:
        claimed = await claim_ready_steps(session, limit=10)
        names = {s.step_name for s in claimed}
        assert "a" not in names


@pytest.mark.asyncio
async def test_mark_step_completed_stores_outputs():
    process_id, _ = await _make_process()
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProcessStep).where(
                ProcessStep.process_id == process_id,
                ProcessStep.step_name == "a",
            )
        )
        step = result.scalar_one()
        await mark_step_completed(session, step, {"summary": "all good"})
        await session.refresh(step)
        assert step.status == "completed"
        assert step.outputs == {"summary": "all good"}
        assert step.finished_at is not None


@pytest.mark.asyncio
async def test_mark_step_failed_retries_under_max_attempts():
    process_id, _ = await _make_process()
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProcessStep).where(
                ProcessStep.process_id == process_id,
                ProcessStep.step_name == "a",
            )
        )
        step = result.scalar_one()
        # Set attempt to 2/5
        step.attempt = 2
        step.max_attempts = 5
        await session.commit()

        result = await mark_step_failed(session, step, "boom")
        await session.refresh(step)
        assert step.status == "retrying"
        assert step.next_retry_at is not None
        # attempt=2 → delay = BACKOFF_SECONDS[1] = 4s
        retry_at = step.next_retry_at
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        delta = (retry_at - datetime.now(timezone.utc)).total_seconds()
        assert 1 < delta < 10


@pytest.mark.asyncio
async def test_mark_step_failed_moves_to_dlq_after_max_attempts():
    process_id, _ = await _make_process()
    async with async_session_maker() as session:
        result = await session.execute(
            select(ProcessStep).where(
                ProcessStep.process_id == process_id,
                ProcessStep.step_name == "a",
            )
        )
        step = result.scalar_one()
        step.attempt = 5
        step.max_attempts = 5
        await session.commit()

        dlq = await mark_step_failed(session, step, "permanent failure")
        await session.refresh(step)
        assert step.status == "failed"
        assert isinstance(dlq, ProcessDLQ)
        assert dlq.reason == "permanent failure"
        assert dlq.retry_count == 5


@pytest.mark.asyncio
async def test_concurrent_workers_claim_disjoint_steps():
    """Two workers claim simultaneously — each gets different steps."""
    process_id, _ = await _make_process()

    async def claim():
        async with async_session_maker() as session:
            return await claim_ready_steps(session, limit=10)

    a, b = await asyncio.gather(claim(), claim())
    a_ids = {str(s.id) for s in a}
    b_ids = {str(s.id) for s in b}
    # Disjoint sets — each worker claimed different steps
    assert a_ids.isdisjoint(b_ids), f"Workers claimed overlapping: {a_ids & b_ids}"
