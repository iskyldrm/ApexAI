"""update_todo / list_todos tool tests."""
import uuid

import pytest
from sqlalchemy import select

from app.db import async_session_maker
from app.models.agent_run import AgentRun
from app.models.conversation import Conversation
from app.agent.tools.base import ToolContext
from app.agent.tools.update_todo import UpdateTodoTool
from app.agent.tools.list_todos import ListTodosTool


async def _make_run() -> str:
    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        run = AgentRun(conversation_id=c.id, role="DEV_BE", status="running")
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return str(run.id)


def _ctx(run_id: str, session):
    return ToolContext(
        agent_run_id=uuid.UUID(run_id),
        user_id="u1",
        org_id=None,
        work_dir="/tmp",
        db_session=session,
    )


@pytest.mark.asyncio
async def test_create_todo():
    run_id = await _make_run()
    async with async_session_maker() as session:
        ctx = _ctx(run_id, session)
        tool = UpdateTodoTool()
        result = await tool.handler(ctx, {"title": "Read app.py", "status": "in_progress"})
    assert result.ok


@pytest.mark.asyncio
async def test_list_todos_for_run():
    run_id = await _make_run()
    async with async_session_maker() as session:
        ctx = _ctx(run_id, session)

        upd = UpdateTodoTool()
        await upd.handler(ctx, {"title": "step 1", "status": "done"})
        await upd.handler(ctx, {"title": "step 2", "status": "pending"})

        lst = ListTodosTool()
        result = await lst.handler(ctx, {})
    assert result.ok
    assert "step 1" in result.output
    assert "step 2" in result.output
    assert "[done]" in result.output
    assert "[pending]" in result.output


@pytest.mark.asyncio
async def test_update_existing_todo_status():
    run_id = await _make_run()
    async with async_session_maker() as session:
        ctx = _ctx(run_id, session)

        upd = UpdateTodoTool()
        r1 = await upd.handler(ctx, {"title": "task", "status": "pending"})
        assert r1.ok
        todo_id = r1.metadata["id"]

        r2 = await upd.handler(ctx, {"id": todo_id, "status": "done"})
        assert r2.ok

        lst = ListTodosTool()
        out = (await lst.handler(ctx, {})).output
    assert "[done]" in out


@pytest.mark.asyncio
async def test_todos_isolated_per_run():
    """A todo created in run A should not appear in run B's list."""
    ctx_a = ToolContext(agent_run_id=uuid.uuid4(), user_id="u1", org_id=None, work_dir="/tmp")
    ctx_b = ToolContext(agent_run_id=uuid.uuid4(), user_id="u1", org_id=None, work_dir="/tmp")

    async with async_session_maker() as session:
        ctx_a.db_session = session
        ctx_b.db_session = session
        upd = UpdateTodoTool()
        await upd.handler(ctx_a, {"title": "only in A", "status": "pending"})

        lst = ListTodosTool()
        out_a = (await lst.handler(ctx_a, {})).output
        out_b = (await lst.handler(ctx_b, {})).output
    assert "only in A" in out_a
    assert "only in A" not in out_b


@pytest.mark.asyncio
async def test_invalid_status_rejected():
    run_id = await _make_run()
    async with async_session_maker() as session:
        ctx = _ctx(run_id, session)
        tool = UpdateTodoTool()
        result = await tool.handler(ctx, {"title": "x", "status": "BOGUS"})
    assert not result.ok


def test_metadata():
    assert UpdateTodoTool().is_mutating is True
    assert UpdateTodoTool().name == "update_todo"
    assert ListTodosTool().is_mutating is False
    assert ListTodosTool().name == "list_todos"
