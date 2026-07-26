"""Phase 9 production-readiness tests — cleanup, cancel, admin endpoints."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session_maker
from app.main import app
from app.models.agent_run import AgentRun
from app.models.conversation import Conversation


def _token(user_id: str, is_platform_admin: bool = False) -> str:
    s = get_settings()
    return pyjwt.encode(
        {
            "sub": user_id,
            "email": "u@test.ai",
            "is_platform_admin": is_platform_admin,
            "orgs": [],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        },
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )


# -------------------- stuck-run cleanup --------------------


@pytest.mark.asyncio
async def test_mark_stuck_runs():
    """A run that started > 1h ago and is still 'running' should be marked stuck."""
    from app.agent.cleanup import mark_stuck_runs

    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        # Fresh run (won't be marked)
        fresh = AgentRun(
            conversation_id=c.id, role="DEV_BE", status="running",
            started_at=datetime.now(timezone.utc),
        )
        # Old run (will be marked)
        old = AgentRun(
            conversation_id=c.id, role="DEV_BE", status="running",
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        session.add_all([fresh, old])
        await session.commit()
        await session.refresh(old)
        old_id = str(old.id)

        await mark_stuck_runs(session)

        # Old run should be marked
        await session.refresh(old)
        assert old.status == "stuck"
        assert old.error is not None
        assert "stuck" in old.error.lower()

        # Fresh run should NOT be marked
        await session.refresh(fresh)
        assert fresh.status == "running"


@pytest.mark.asyncio
async def test_mark_stuck_runs_handles_no_stuck():
    from app.agent.cleanup import mark_stuck_runs

    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="finished")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        session.add(AgentRun(
            conversation_id=c.id, role="DEV_BE", status="finished",
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        ))
        await session.commit()

    async with async_session_maker() as session:
        # Finished run should not be touched regardless of age
        count = await mark_stuck_runs(session)
        assert count == 0


# -------------------- cancel endpoint --------------------


@pytest.mark.asyncio
async def test_cancel_run_via_api():
    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        run = AgentRun(conversation_id=c.id, role="DEV_BE", status="running")
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = str(run.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/agent/runs/{run_id}/cancel",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    async with async_session_maker() as session:
        run = await session.get(AgentRun, run_id)
        assert run.status == "cancelled"
        assert run.error == "Cancelled by user"


@pytest.mark.asyncio
async def test_cancel_finished_run_returns_400():
    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="finished")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        run = AgentRun(conversation_id=c.id, role="DEV_BE", status="finished")
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = str(run.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/agent/runs/{run_id}/cancel",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_cancel_missing_run_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/agent/runs/{uuid.uuid4()}/cancel",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 404


# -------------------- admin endpoints --------------------


@pytest.mark.asyncio
async def test_admin_stats_requires_platform_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/agent/admin/stats",
            cookies={"access_token": _token(str(uuid.uuid4()), is_platform_admin=False)},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_stats_returns_aggregates():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/agent/admin/stats",
            cookies={"access_token": _token(str(uuid.uuid4()), is_platform_admin=True)},
        )
    assert r.status_code == 200
    body = r.json()
    assert "total_runs" in body
    assert "total_input_tokens" in body
    assert "total_output_tokens" in body
    assert "by_status" in body


@pytest.mark.asyncio
async def test_admin_cleanup_requires_platform_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/agent/admin/cleanup",
            cookies={"access_token": _token(str(uuid.uuid4()), is_platform_admin=False)},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_cleanup_marks_stuck_runs():
    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="running")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        old = AgentRun(
            conversation_id=c.id, role="DEV_BE", status="running",
            started_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
        session.add(old)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/agent/admin/cleanup",
            cookies={"access_token": _token(str(uuid.uuid4()), is_platform_admin=True)},
        )
    assert r.status_code == 200
    assert r.json()["marked_stuck"] >= 1
