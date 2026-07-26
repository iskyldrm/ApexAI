"""ask_user tool tests — pauses the agent loop for human input."""
import uuid
from unittest.mock import MagicMock

import pytest

from app.agent.tools.ask_user import AskUserTool
from app.agent.tools.base import ToolContext


def _ctx():
    return ToolContext(agent_run_id=uuid.uuid4(), user_id="u1", org_id=None, work_dir="/tmp")


@pytest.mark.asyncio
async def test_ask_user_returns_question_envelope():
    """Without an answer provider, returns a 'pending' envelope for the runtime."""
    tool = AskUserTool()
    result = await tool.handler(_ctx(), {
        "question": "Which ORM should we use?",
        "options": ["SQLAlchemy", "SQLModel", "Tortoise"],
    })
    assert result.ok
    assert "question" in result.metadata
    assert "options" in result.metadata
    assert result.metadata["status"] == "pending"


@pytest.mark.asyncio
async def test_ask_user_with_answer_provider_returns_choice():
    """When the runtime injects an answer (e.g. via SSE), the tool returns it."""
    # Simulate an answer provider that returns immediately
    async def answer_provider(_question, _options):
        return "SQLModel"

    tool = AskUserTool(answer_provider=answer_provider)
    result = await tool.handler(_ctx(), {
        "question": "Which ORM?",
        "options": ["SQLAlchemy", "SQLModel", "Tortoise"],
    })
    assert result.ok
    assert "SQLModel" in result.output
    assert result.metadata["answer"] == "SQLModel"


@pytest.mark.asyncio
async def test_ask_user_requires_options_or_free_text():
    tool = AskUserTool()
    result = await tool.handler(_ctx(), {"question": "hi"})
    # free_text defaults to True → user can type anything → should succeed
    assert result.ok


@pytest.mark.asyncio
async def test_ask_user_metadata():
    tool = AskUserTool()
    assert tool.is_mutating is False
    assert tool.name == "ask_user"
    assert "user_input:read" in tool.required_permissions
