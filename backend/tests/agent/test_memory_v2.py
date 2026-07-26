"""Phase 7 memory improvement tests — token-aware trim, branching, export."""
import json
import uuid

import pytest

from app.agent.memory import (
    Message,
    branch,
    count_message_tokens,
    count_tokens,
    export_conversation,
    extractive_summary,
    get_token_budget_for_role,
    maybe_summarize,
    token_aware_trim,
    trim,
)


# -------------------- Task 40: token-aware trim --------------------


def test_count_tokens_returns_positive():
    assert count_tokens("hello world") > 0


def test_count_message_tokens_includes_overhead():
    msgs = [Message(role="user", content="hi")]
    # 4 overhead + content tokens
    assert count_message_tokens(msgs) > 4


def test_token_aware_trim_keeps_recent_messages():
    msgs = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="x" * 1000),
        Message(role="assistant", content="y" * 1000),
        Message(role="user", content="z" * 1000),
        Message(role="assistant", content="final answer"),
    ]
    trimmed = token_aware_trim(msgs, max_tokens=500, model="gpt-4o")
    # Last message should always be kept (or close to it)
    assert trimmed[-1].content == "final answer"
    # Some messages should have been dropped
    assert len(trimmed) < len(msgs)


def test_token_aware_trim_no_op_under_budget():
    msgs = [Message(role="user", content="short")]
    trimmed = token_aware_trim(msgs, max_tokens=10_000)
    assert len(trimmed) == 1


def test_token_aware_trim_always_keeps_system():
    msgs = [
        Message(role="system", content="sys" * 500),
        Message(role="user", content="x" * 5000),
        Message(role="assistant", content="y" * 5000),
    ]
    trimmed = token_aware_trim(msgs, max_tokens=200, model="gpt-4o")
    # System message should be present (or its summary)
    sys_present = any(m.role == "system" for m in trimmed)
    assert sys_present


def test_get_token_budget_per_role():
    assert get_token_budget_for_role("DEV_BE") == 16_000
    assert get_token_budget_for_role("PM") == 4_000
    assert get_token_budget_for_role("MGR") == 4_000


# -------------------- Task 41: improved extractive summary --------------------


def test_extractive_summary_captures_multiple_categories():
    msgs = [
        Message(
            role="assistant",
            content="I'll use FastAPI for the backend. Decided to use Postgres for storage.",
            tool_calls=[{"name": "write_file", "arguments": {"path": "/tmp/a.py"}}],
        ),
        Message(role="tool", content="Traceback: ImportError failed"),
        Message(role="assistant", content="Let me read /tmp/b.py to debug."),
    ]
    s = extractive_summary(msgs)
    assert "/tmp/a.py" in s["files_written"]
    assert "/tmp/b.py" in s["files_read"]
    assert len(s["decisions"]) >= 2
    assert len(s["errors"]) >= 1


# -------------------- Task 42: branching --------------------


@pytest.mark.asyncio
async def test_branch_creates_child_with_parent_id():
    """A branched message has its parent_id set."""
    from app.db import async_session_maker
    from app.models.conversation import Conversation
    from app.agent.memory import ConversationStore

    async with async_session_maker() as session:
        c = Conversation(role="MGR", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        store = ConversationStore(session, c.id)
        # Create parent
        parent = Message(role="user", content="delegate to DEV")
        await store.append(parent, sequence=0)
        # Branch from it
        child = await branch(store, parent, child_role="DEV_BE")
        assert child.parent_id == parent.id
        assert "DEV_BE" in child.content


# -------------------- Task 43: export --------------------


def test_export_returns_serializable_dict():
    msgs = [
        Message(role="user", content="hi", input_tokens=5),
        Message(role="assistant", content="hello", output_tokens=3),
    ]
    out = export_conversation(msgs)
    assert out["message_count"] == 2
    assert len(out["messages"]) == 2
    assert out["messages"][0]["role"] == "user"
    # Should be JSON-serializable
    json.dumps(out)


def test_export_preserves_parent_links():
    parent = Message(role="user", content="p")
    child = Message(role="assistant", content="c", parent_id=parent.id)
    out = export_conversation([parent, child])
    assert out["messages"][0]["parent_id"] is None
    assert out["messages"][1]["parent_id"] is not None
