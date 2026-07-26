"""Conversation + AgentRun model tests."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db import async_session_maker
from app.models.agent_run import AgentRun
from app.models.conversation import Conversation, ConversationMessage


@pytest.mark.asyncio
async def test_create_conversation():
    async with async_session_maker() as session:
        c = Conversation(
            role="DEV_BE",
            status="running",
            user_id=str(uuid.uuid4()),
            org_id=str(uuid.uuid4()),
        )
        session.add(c)
        await session.commit()
        await session.refresh(c)
        assert c.id is not None
        assert c.role == "DEV_BE"
        assert c.status == "running"
        assert c.total_input_tokens == 0


@pytest.mark.asyncio
async def test_append_messages_to_conversation():
    async with async_session_maker() as session:
        c = Conversation(role="ANL", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)

        for i, role in enumerate(("user", "assistant", "tool")):
            m = ConversationMessage(
                conversation_id=c.id,
                role=role,
                content=f"msg {i}",
                sequence=i,
            )
            session.add(m)
        await session.commit()

        result = await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == c.id)
            .order_by(ConversationMessage.sequence)
        )
        msgs = result.scalars().all()
        assert len(msgs) == 3
        assert [m.role for m in msgs] == ["user", "assistant", "tool"]


@pytest.mark.asyncio
async def test_create_agent_run_with_tokens():
    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)

        run = AgentRun(
            conversation_id=c.id,
            role="DEV_BE",
            provider="anthropic",
            model="claude-sonnet-4-5",
            status="finished",
            input_tokens=1500,
            output_tokens=800,
            cost_usd=0.045,
            duration_ms=12_345,
            steps=7,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        assert run.cost_usd == 0.045
        assert run.duration_ms == 12_345
        assert run.steps == 7


@pytest.mark.asyncio
async def test_conversation_metadata_jsonb():
    async with async_session_maker() as session:
        c = Conversation(
            role="MGR",
            status="running",
            meta={"plan": "step 1 then 2", "priority": "high"},
        )
        session.add(c)
        await session.commit()
        await session.refresh(c)
        assert c.meta == {"plan": "step 1 then 2", "priority": "high"}


@pytest.mark.asyncio
async def test_message_tool_calls_jsonb():
    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        m = ConversationMessage(
            conversation_id=c.id,
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "name": "read_file",
                    "arguments": {"path": "/tmp/x.py"},
                }
            ],
            tool_name="read_file",
            tool_call_id="call_1",
            sequence=0,
        )
        session.add(m)
        await session.commit()
        await session.refresh(m)
        assert m.tool_calls is not None
        assert m.tool_calls[0]["name"] == "read_file"


@pytest.mark.asyncio
async def test_message_parent_message_branching():
    async with async_session_maker() as session:
        c = Conversation(role="MGR", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        parent = ConversationMessage(
            conversation_id=c.id, role="user", content="delegate", sequence=0
        )
        session.add(parent)
        await session.commit()
        await session.refresh(parent)
        child = ConversationMessage(
            conversation_id=c.id,
            role="assistant",
            content="running sub-agent",
            parent_message_id=parent.id,
            sequence=1,
        )
        session.add(child)
        await session.commit()
        await session.refresh(child)
        assert child.parent_message_id == parent.id
