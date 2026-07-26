"""Conversation memory tests — pure Python (no DB)."""
import uuid

import pytest

from app.agent.memory import (
    ConversationStore,
    Message,
    extractive_summary,
    maybe_summarize,
    trim,
)


def _msgs(n: int) -> list[Message]:
    """Create n alternating user/assistant messages."""
    out = []
    for i in range(n):
        out.append(Message(role="user" if i % 2 == 0 else "assistant", content=f"m{i}"))
    return out


def test_trim_keeps_recent():
    msgs = _msgs(50)
    trimmed = trim(msgs, max_messages=10)
    assert len(trimmed) == 10
    assert trimmed[-1].content == "m49"


def test_trim_preserves_system_message():
    msgs = [Message(role="system", content="You are a helpful agent.")]
    msgs += _msgs(40)
    trimmed = trim(msgs, max_messages=10)
    assert trimmed[0].role == "system"
    assert trimmed[0].content.startswith("You are")
    # 1 system + 10 recent = 11
    assert len(trimmed) == 11


def test_trim_no_op_when_under_limit():
    msgs = _msgs(5)
    assert trim(msgs, max_messages=10) == msgs


def test_extractive_summary_files_read():
    msgs = [
        Message(role="assistant", content="I'll read `/tmp/app.py` first"),
        Message(role="tool", content="contents of /tmp/app.py", tool_name="read_file"),
    ]
    s = extractive_summary(msgs)
    assert "/tmp/app.py" in s["files_read"]


def test_extractive_summary_files_written():
    msgs = [
        Message(
            role="assistant",
            content="writing file",
            tool_calls=[
                {"name": "write_file", "arguments": {"path": "/tmp/new.py"}}
            ],
        )
    ]
    s = extractive_summary(msgs)
    assert "/tmp/new.py" in s["files_written"]


def test_extractive_summary_decisions():
    msgs = [
        Message(role="assistant", content="I'll use FastAPI for the backend."),
        Message(role="assistant", content="Decided to use Postgres for storage."),
    ]
    s = extractive_summary(msgs)
    assert len(s["decisions"]) >= 2


def test_extractive_summary_errors():
    msgs = [
        Message(role="tool", content="Traceback: ImportError: failed to import x"),
    ]
    s = extractive_summary(msgs)
    assert len(s["errors"]) >= 1


def test_maybe_summarize_under_threshold_passthrough():
    msgs = _msgs(10)
    out = maybe_summarize(msgs, threshold=50)
    assert out == msgs


def test_maybe_summarize_over_threshold_inserts():
    msgs = [Message(role="user", content="read /tmp/a.py")] * 40
    msgs += [Message(role="assistant", content=f"step {i}", tool_calls=[
        {"name": "write_file", "arguments": {"path": f"/tmp/x{i}.py"}}
    ]) for i in range(20)]
    out = maybe_summarize(msgs, threshold=50)
    assert any(m.role == "system" and "[Summary of" in m.content for m in out)
    # final messages preserved
    assert "step 19" in out[-1].content


def test_message_to_llm_dict_assistant_with_tool_calls():
    m = Message(
        role="assistant",
        content="",
        tool_calls=[{"id": "abc", "name": "read_file", "arguments": {"path": "/x"}}],
    )
    d = m.to_llm_dict()
    assert d["role"] == "assistant"
    assert d["tool_calls"][0]["name"] == "read_file"


def test_message_to_llm_dict_tool_response():
    m = Message(
        role="tool",
        content="file contents",
        tool_call_id="abc",
        tool_name="read_file",
    )
    d = m.to_llm_dict()
    assert d["role"] == "tool"
    assert d["tool_call_id"] == "abc"
    assert d["name"] == "read_file"


@pytest.mark.asyncio
async def test_conversation_store_append_and_get():
    """Round-trip with the DB (uses the existing async_session_maker)."""
    from app.db import async_session_maker
    from app.models.conversation import Conversation

    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        store = ConversationStore(session, c.id)
        await store.append(
            Message(role="user", content="hi"), sequence=0
        )
        await store.append(
            Message(role="assistant", content="hello"), sequence=1
        )
        await session.commit()

        msgs = await store.get_messages()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].content == "hello"
