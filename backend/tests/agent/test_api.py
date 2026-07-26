"""Agent REST API tests — uses mocked LiteLLMClient."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


def _token(user_id: str, is_platform_admin: bool = False, orgs: list | None = None) -> str:
    settings = get_settings()
    return pyjwt.encode(
        {
            "sub": user_id,
            "email": "u@test.ai",
            "is_platform_admin": is_platform_admin,
            "orgs": orgs or [],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _mock_llm_response(content: str = "done", tool_calls=None, finish_reason: str = "stop"):
    from app.agent.llm.litellm_client import LLMResponse

    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        finish_reason=finish_reason,
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
        model="gpt-4o",
    )


@pytest.mark.asyncio
async def test_converse_invalid_role_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/agent/converse",
            json={"role": "INVALID", "prompt": "x", "work_dir": "/tmp"},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_converse_unauthenticated_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/agent/converse",
            json={"role": "ANL", "prompt": "x", "work_dir": "/tmp"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_converse_runs_agent_loop(tmp_path):
    """Successful run returns a ConverseResponse with agent_run_id + summary."""
    work = tmp_path / "work"
    work.mkdir()

    with patch("app.agent.api.routes.LiteLLMClient") as MockLLM:
        llm = MagicMock()
        llm.completion = AsyncMock(side_effect=[
            _mock_llm_response("the answer is 42", finish_reason="stop"),
        ])
        MockLLM.return_value = llm

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/agent/converse",
                json={"role": "ANL", "prompt": "what is the answer?", "work_dir": str(work)},
                cookies={"access_token": _token(str(uuid.uuid4()))},
            )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["finish_reason"] == "finished"
    assert body["success"] is True
    assert "42" in body["summary"]


@pytest.mark.asyncio
async def test_get_run_returns_messages(tmp_path):
    """GET /agent/runs/{id} returns the run + its messages."""
    from app.db import async_session_maker
    from app.models.conversation import Conversation
    from app.models.agent_run import AgentRun

    work = tmp_path / "work"
    work.mkdir()

    # Create a run manually
    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="finished")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        run = AgentRun(
            conversation_id=c.id,
            role="DEV_BE",
            model="gpt-4o",
            status="finished",
            steps=3,
            input_tokens=100,
            output_tokens=50,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = str(run.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/agent/runs/{run_id}",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == run_id
    assert body["status"] == "finished"
    assert body["steps"] == 3


@pytest.mark.asyncio
async def test_get_run_404_when_missing():
    transport = ASGITransport(app=app)
    fake_id = str(uuid.uuid4())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/agent/runs/{fake_id}",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_runs_filters_by_role(tmp_path):
    from app.db import async_session_maker
    from app.models.conversation import Conversation
    from app.models.agent_run import AgentRun

    async with async_session_maker() as session:
        c1 = Conversation(role="ANL", status="finished")
        c2 = Conversation(role="QA", status="finished")
        session.add_all([c1, c2])
        await session.commit()
        await session.refresh(c1)
        await session.refresh(c2)
        session.add_all([
            AgentRun(conversation_id=c1.id, role="ANL", model="gpt-4o", status="finished", steps=1),
            AgentRun(conversation_id=c2.id, role="QA", model="gpt-4o", status="finished", steps=1),
        ])
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/agent/runs?role=ANL",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200
    body = r.json()
    roles = {it["role"] for it in body["items"]}
    assert roles <= {"ANL"}  # subset — only ANL runs returned


@pytest.mark.asyncio
async def test_converse_stream_emits_sse(tmp_path):
    """Stream variant returns text/event-stream and at least one finished event."""
    work = tmp_path / "work"
    work.mkdir()

    with patch("app.agent.api.routes.LiteLLMClient") as MockLLM:
        llm = MagicMock()
        llm.completion = AsyncMock(side_effect=[
            _mock_llm_response("42", finish_reason="stop"),
        ])
        MockLLM.return_value = llm

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/v1/agent/converse/stream",
                json={"role": "ANL", "prompt": "x", "work_dir": str(work)},
                cookies={"access_token": _token(str(uuid.uuid4()))},
            )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    # Should have at least agent.started and agent.finished
    assert "event: agent.started" in body
    assert "event: agent.finished" in body
