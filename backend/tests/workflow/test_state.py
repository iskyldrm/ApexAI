"""State machine + event sourcing tests."""
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.db import async_session_maker
from app.models.process import Process, ProcessEvent, ProcessStep
from app.workflow.state import (
    InvalidTransition,
    can_transition_process,
    can_transition_step,
    derive_process_status_from_events,
    transition_process,
    transition_step,
)


async def _make_process() -> Process:
    async with async_session_maker() as session:
        p = Process(
            name=f"sm-{uuid.uuid4().hex[:6]}",
            definition={"name": "x", "steps": [{"name": "a", "role": "ANL", "prompt": "p"}], "edges": []},
            status="draft",
            org_id=str(uuid.uuid4()),
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return p


# -------------------- Pure-function transition table --------------------


def test_valid_process_transitions():
    assert can_transition_process("draft", "queued")
    assert can_transition_process("queued", "running")
    assert can_transition_process("running", "completed")
    assert can_transition_process("running", "paused")
    assert can_transition_process("paused", "running")
    assert can_transition_process("stuck", "running")


def test_invalid_process_transitions():
    # Terminal states can't transition
    assert not can_transition_process("completed", "running")
    assert not can_transition_process("failed", "running")
    assert not can_transition_process("cancelled", "running")
    # draft can't go straight to running
    assert not can_transition_process("draft", "running")
    assert not can_transition_process("draft", "completed")


def test_valid_step_transitions():
    assert can_transition_step("pending", "queued")
    assert can_transition_step("pending", "running")
    assert can_transition_step("running", "completed")
    assert can_transition_step("running", "failed")
    assert can_transition_step("running", "retrying")
    assert can_transition_step("retrying", "pending")


def test_invalid_step_transitions():
    assert not can_transition_step("completed", "running")
    assert not can_transition_step("failed", "pending")
    assert not can_transition_step("cancelled", "running")


# -------------------- transition_process + event emission --------------------


@pytest.mark.asyncio
async def test_transition_process_emits_event():
    p = await _make_process()
    async with async_session_maker() as session:
        p = await session.get(Process, p.id)
        ev = await transition_process(session, p, "queued", actor_id="u1")
        await session.commit()
    assert ev.event_type == "process.queued"
    assert ev.payload["from"] == "draft"
    assert ev.payload["to"] == "queued"
    assert ev.actor_id == "u1"


@pytest.mark.asyncio
async def test_transition_process_invalid_raises():
    p = await _make_process()
    async with async_session_maker() as session:
        p = await session.get(Process, p.id)
        # draft → running is not allowed
        with pytest.raises(InvalidTransition):
            await transition_process(session, p, "running")
        # Status unchanged
        assert p.status == "draft"


@pytest.mark.asyncio
async def test_transition_process_full_lifecycle():
    p = await _make_process()
    async with async_session_maker() as session:
        p = await session.get(Process, p.id)
        await transition_process(session, p, "queued")
        await transition_process(session, p, "running")
        await session.commit()
        await session.refresh(p)
        assert p.status == "running"
        assert p.started_at is not None

    async with async_session_maker() as session:
        p = await session.get(Process, p.id)
        await transition_process(session, p, "completed")
        await session.commit()
        await session.refresh(p)
        assert p.status == "completed"
        assert p.finished_at is not None


# -------------------- transition_step + event emission --------------------


@pytest.mark.asyncio
async def test_transition_step_emits_event():
    p = await _make_process()
    async with async_session_maker() as session:
        s = ProcessStep(
            process_id=p.id,
            step_name="a",
            role="ANL",
            status="pending",
            prompt_template="p",
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        step_id = s.id

    async with async_session_maker() as session:
        s = await session.get(ProcessStep, step_id)
        ev = await transition_step(session, s, "queued")
        await session.commit()
    assert ev.event_type == "step.queued"
    assert ev.step_id == step_id
    assert ev.payload["from"] == "pending"
    assert ev.payload["to"] == "queued"
    assert ev.payload["step_name"] == "a"


@pytest.mark.asyncio
async def test_transition_step_terminal_blocks_further_transitions():
    p = await _make_process()
    async with async_session_maker() as session:
        s = ProcessStep(
            process_id=p.id, step_name="a", role="ANL",
            status="pending", prompt_template="p",
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        s_id = s.id

    async with async_session_maker() as session:
        s = await session.get(ProcessStep, s_id)
        await transition_step(session, s, "running")
        await transition_step(session, s, "completed")
        await session.commit()
        await session.refresh(s)
        assert s.status == "completed"
        # completed is terminal
        with pytest.raises(InvalidTransition):
            await transition_step(session, s, "running")


# -------------------- Event replay --------------------


def test_derive_process_status_from_events():
    events = [
        ProcessEvent(event_type="process.queued", payload={}),
        ProcessEvent(event_type="process.running", payload={}),
        ProcessEvent(event_type="process.completed", payload={}),
    ]
    assert derive_process_status_from_events(events) == "completed"


def test_derive_process_status_empty():
    assert derive_process_status_from_events([]) == "draft"


def test_derive_process_status_ignores_step_events():
    events = [
        ProcessEvent(event_type="step.queued", payload={}),
        ProcessEvent(event_type="step.completed", payload={}),
    ]
    # No process.* events → still "draft"
    assert derive_process_status_from_events(events) == "draft"
