"""Tests for agent run checkpoints and resume (A.9-A.12)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.agent.checkpoint import (
    CHECKPOINT_EVERY_N_STEPS,
    list_resumable_runs,
    load_latest_checkpoint,
    mark_stuck_runs_interrupted,
    save_checkpoint,
)
from app.agent.llm.litellm_client import LLMResponse
from app.agent.roles import Role
from app.agent.runtime import AgentLoop, AgentLoopConfig
from app.db import async_session_maker


def _text_response(text: str, tool_calls=None, input_tokens=10, output_tokens=5) -> LLMResponse:
    return LLMResponse(
        content=text,
        tool_calls=tool_calls or [],
        finish_reason="tool_calls" if tool_calls else "stop",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=0.001,
        model="gpt-4o",
    )


def _tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    return {"id": call_id, "name": name, "arguments": args}


def _make_llm_client(responses: list[LLMResponse]):
    client = MagicMock()
    client.completion = AsyncMock(side_effect=responses)
    return client


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


# -------------------- Pure checkpoint service tests --------------------


@pytest.mark.asyncio
async def test_save_and_load_checkpoint():
    async with async_session_maker() as session:
        # Need a parent AgentRun to satisfy the FK
        from app.agent.runtime import AgentLoop  # noqa: F401
        from app.models.agent_run import AgentRun
        from app.models.conversation import Conversation

        conv = Conversation(
            role=Role.ANALYST.value,
            status="running",
            user_id=None,
            org_id=None,
        )
        session.add(conv)
        await session.flush()

        run = AgentRun(
            conversation_id=conv.id,
            user_id=None,
            org_id=None,
            role=Role.ANALYST.value,
            model="gpt-4o",
            status="running",
        )
        session.add(run)
        await session.commit()

        ck = await save_checkpoint(
            session,
            agent_run_id=run.id,
            step=10,
            state={"input_tokens": 100, "output_tokens": 50, "intentional_files": ["a.py"]},
        )
        await session.commit()

        loaded = await load_latest_checkpoint(session, run.id)
        assert loaded is not None
        assert loaded.step == 10
        assert loaded.state["input_tokens"] == 100
        assert loaded.state["intentional_files"] == ["a.py"]


@pytest.mark.asyncio
async def test_load_latest_returns_most_recent_checkpoint():
    async with async_session_maker() as session:
        from app.models.agent_run import AgentRun
        from app.models.conversation import Conversation

        conv = Conversation(
            role=Role.ANALYST.value, status="running", user_id=None, org_id=None
        )
        session.add(conv)
        await session.flush()
        run = AgentRun(
            conversation_id=conv.id, user_id=None, org_id=None,
            role=Role.ANALYST.value, model="gpt-4o", status="running",
        )
        session.add(run)
        await session.commit()

        # Save 3 checkpoints
        for s in [3, 7, 12]:
            await save_checkpoint(session, agent_run_id=run.id, step=s, state={"step": s})
        await session.commit()

        latest = await load_latest_checkpoint(session, run.id)
        assert latest is not None
        assert latest.step == 12


@pytest.mark.asyncio
async def test_load_latest_returns_none_when_no_checkpoints():
    async with async_session_maker() as session:
        ck = await load_latest_checkpoint(session, uuid4())
        assert ck is None


@pytest.mark.asyncio
async def test_mark_stuck_runs_interrupted():
    async with async_session_maker() as session:
        from app.models.agent_run import AgentRun
        from app.models.conversation import Conversation

        # Old running run (stuck)
        old_conv = Conversation(
            role=Role.ANALYST.value, status="running", user_id=None, org_id=None
        )
        session.add(old_conv)
        await session.flush()
        old_run = AgentRun(
            conversation_id=old_conv.id, user_id=None, org_id=None,
            role=Role.ANALYST.value, model="x", status="running",
            started_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
        )
        session.add(old_run)

        # Fresh running run (should NOT be marked)
        fresh_conv = Conversation(
            role=Role.ANALYST.value, status="running", user_id=None, org_id=None
        )
        session.add(fresh_conv)
        await session.flush()
        fresh_run = AgentRun(
            conversation_id=fresh_conv.id, user_id=None, org_id=None,
            role=Role.ANALYST.value, model="x", status="running",
            started_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5),
        )
        session.add(fresh_run)
        await session.commit()

        n = await mark_stuck_runs_interrupted(session, threshold_seconds=3600)
        assert n == 1

        await session.refresh(old_run)
        await session.refresh(fresh_run)
        assert old_run.status == "interrupted"
        assert fresh_run.status == "running"


@pytest.mark.asyncio
async def test_list_resumable_runs():
    async with async_session_maker() as session:
        from app.models.agent_run import AgentRun
        from app.models.conversation import Conversation

        # Create one interrupted and one running — only interrupted should appear
        for status in ["interrupted", "running", "awaiting_approval", "finished"]:
            conv = Conversation(
                role=Role.ANALYST.value, status=status, user_id=None, org_id=None
            )
            session.add(conv)
            await session.flush()
            run = AgentRun(
                conversation_id=conv.id, user_id=None, org_id=None,
                role=Role.ANALYST.value, model="x", status=status,
            )
            session.add(run)
        await session.commit()

        resumable = await list_resumable_runs(session)
        statuses = {r.status for r in resumable}
        assert "interrupted" in statuses
        assert "awaiting_approval" in statuses
        assert "running" not in statuses
        assert "finished" not in statuses


# -------------------- AgentLoop integration --------------------


@pytest.mark.asyncio
async def test_checkpoint_saved_every_n_steps(work_dir):
    """A multi-step run must produce at least one checkpoint."""
    from pathlib import Path

    Path(work_dir, "x.txt").write_text("hi\n")

    # 6 responses each with a tool call (read_file) — keeps the loop running
    # through step 5 at minimum. CHECKPOINT_EVERY_N_STEPS=5 means a
    # checkpoint is saved when ``steps % 5 == 0``.
    responses = []
    for i in range(6):
        responses.append(
            _text_response(
                f"step {i}",
                input_tokens=5,
                output_tokens=2,
                tool_calls=[_tool_call("read_file", {"path": f"{work_dir}/x.txt"}, f"call_{i}")],
            )
        )
    # 7th response: plain text (ends the loop)
    responses.append(_text_response("done"))

    async with async_session_maker() as session:
        llm = _make_llm_client(responses)
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(
            role=Role.ANALYST,
            user_prompt="do many steps",
            work_dir=work_dir,
        )
        result = await loop.run(cfg)

        # At least one checkpoint should exist for this run
        from app.models.agent_run import AgentRun
        from app.models.agent_run_checkpoint import AgentRunCheckpoint
        from sqlalchemy import select

        run_id = result.agent_run_id
        stmt = select(AgentRunCheckpoint).where(
            AgentRunCheckpoint.agent_run_id == run_id
        )
        result_ck = await session.execute(stmt)
        cks = list(result_ck.scalars().all())
        assert len(cks) >= 1
        # Each checkpoint has the expected state fields
        for ck in cks:
            assert "input_tokens" in ck.state
            assert "output_tokens" in ck.state
            assert ck.step > 0


@pytest.mark.asyncio
async def test_resume_run_continues_from_checkpoint(work_dir):
    """A resumed run must NOT create a new conversation — it must reuse the existing one."""
    # Step 1: Run to completion (text-only responses, 3 steps)
    responses_initial = [
        _text_response("thinking", input_tokens=5, output_tokens=2),
        _text_response("almost there", input_tokens=5, output_tokens=2),
        _text_response("done with task", input_tokens=5, output_tokens=2),
    ]

    async with async_session_maker() as session:
        llm = _make_llm_client(responses_initial)
        loop = AgentLoop(llm_client=llm, session=session)
        cfg = AgentLoopConfig(
            role=Role.ANALYST,
            user_prompt="task",
            work_dir=work_dir,
        )
        result = await loop.run(cfg)

        original_conv_id = result.conversation_id
        original_run_id = result.agent_run_id
        original_steps = result.steps

        # Step 2: Mark run as 'interrupted' (simulating crash)
        from app.models.agent_run import AgentRun

        run = await session.get(AgentRun, original_run_id)
        run.status = "interrupted"
        await session.commit()

        # Step 3: Resume the run — should reuse the same conversation + run
        responses_resume = [_text_response("resumed and done")]
        llm2 = _make_llm_client(responses_resume)
        loop2 = AgentLoop(llm_client=llm2, session=session)
        cfg2 = AgentLoopConfig(
            role=Role.ANALYST,
            user_prompt="task",  # ignored — using resume
            work_dir=work_dir,
            resume_conversation_id=original_conv_id,
            resume_agent_run_id=original_run_id,
        )
        result2 = await loop2.run(cfg2)

        # The resume must reuse the same conversation + run
        assert result2.conversation_id == original_conv_id
        assert result2.agent_run_id == original_run_id
        # Steps should not restart from 0 (state was seeded from checkpoint)
        assert result2.steps >= original_steps