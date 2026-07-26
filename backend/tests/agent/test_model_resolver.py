"""Tests for model_resolver and resume/export endpoints."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.agent.model_resolver import resolve_default_model
from app.config import get_settings
from app.db import async_session_maker
from app.main import app
from app.models.conversation import Conversation, ConversationMessage
from app.models.agent_run import AgentRun
from app.models.org import Org
from app.models.user import User
from app.models.setting import Setting


def _token(user_id: str, is_platform_admin: bool = False, orgs: list | None = None) -> str:
    s = get_settings()
    return pyjwt.encode(
        {
            "sub": user_id,
            "email": "u@test.ai",
            "is_platform_admin": is_platform_admin,
            "orgs": orgs or [],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        },
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )


# -------------------- Task 60: model_resolver --------------------


@pytest.mark.asyncio
async def test_resolve_returns_request_override_first():
    from app.agent.roles import Role

    async with async_session_maker() as session:
        m = await resolve_default_model(
            session, role=Role.DEVELOPER_BE, org_id=None, user_id=None,
            request_override="gpt-5-turbo",
        )
    assert m == "gpt-5-turbo"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_role_default_when_no_settings():
    from app.agent.roles import Role

    async with async_session_maker() as session:
        m = await resolve_default_model(
            session, role=Role.DEVELOPER_BE, org_id=None, user_id="user-1",
        )
    # No settings exist for this user/org → fall back to role default
    assert m == "claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_resolve_uses_org_setting():
    from app.agent.roles import Role

    # Create a real org and set its default model
    async with async_session_maker() as session:
        org = Org(slug=f"mr-{uuid.uuid4().hex[:6]}", name="MR", status="active")
        session.add(org)
        await session.commit()
        await session.refresh(org)
        org_id = str(org.id)
        setting = Setting(
            scope="org",
            scope_id=org_id,
            key="ai.default_model",
            value={"model": "gpt-3.5-turbo"},
            enforced_by_admin=True,
        )
        session.add(setting)
        await session.commit()

    async with async_session_maker() as session:
        m = await resolve_default_model(
            session, role=Role.DEVELOPER_BE, org_id=org_id, user_id="u1",
        )
    assert m == "gpt-3.5-turbo"


@pytest.mark.asyncio
async def test_resolve_user_setting_overrides_org():
    from app.agent.roles import Role

    async with async_session_maker() as session:
        user = User(
            email=f"mr-user-{uuid.uuid4().hex[:6]}@apex.ai",
            password_hash="x",
            full_name="T",
        )
        org = Org(slug=f"mr-{uuid.uuid4().hex[:6]}", name="MR", status="active")
        session.add_all([user, org])
        await session.commit()
        await session.refresh(user)
        await session.refresh(org)
        user_id = str(user.id)
        org_id = str(org.id)
        # Org setting
        session.add(Setting(
            scope="org", scope_id=org_id, key="ai.default_model",
            value={"model": "gpt-3.5-turbo"}, enforced_by_admin=False,
        ))
        # User setting (more specific)
        session.add(Setting(
            scope="user", scope_id=user_id, key="ai.default_model",
            value={"model": "claude-opus-4-1"}, enforced_by_admin=False,
        ))
        await session.commit()

    async with async_session_maker() as session:
        m = await resolve_default_model(
            session, role=Role.DEVELOPER_BE, org_id=org_id, user_id=user_id,
        )
    # User (more specific) wins
    assert m == "claude-opus-4-1"


@pytest.mark.asyncio
async def test_resolve_user_blocked_by_enforced_org():
    from app.agent.roles import Role

    async with async_session_maker() as session:
        user = User(
            email=f"mr-{uuid.uuid4().hex[:6]}@apex.ai",
            password_hash="x", full_name="T",
        )
        org = Org(slug=f"mr-{uuid.uuid4().hex[:6]}", name="MR", status="active")
        session.add_all([user, org])
        await session.commit()
        await session.refresh(user)
        await session.refresh(org)
        user_id, org_id = str(user.id), str(org.id)
        session.add(Setting(
            scope="org", scope_id=org_id, key="ai.default_model",
            value={"model": "gpt-3.5-turbo"}, enforced_by_admin=True,
        ))
        session.add(Setting(
            scope="user", scope_id=user_id, key="ai.default_model",
            value={"model": "claude-opus-4-1"}, enforced_by_admin=False,
        ))
        await session.commit()

    async with async_session_maker() as session:
        m = await resolve_default_model(
            session, role=Role.DEVELOPER_BE, org_id=org_id, user_id=user_id,
        )
    # Org enforced → user override ignored
    assert m == "gpt-3.5-turbo"


# -------------------- Task 36-37: export + resume endpoints --------------------


@pytest.mark.asyncio
async def test_export_run_returns_messages():
    async with async_session_maker() as session:
        c = Conversation(role="DEV_BE", status="finished")
        session.add(c)
        await session.commit()
        await session.refresh(c)
        run = AgentRun(conversation_id=c.id, role="DEV_BE", status="finished")
        session.add(run)
        await session.commit()
        await session.refresh(run)
        session.add(ConversationMessage(
            conversation_id=c.id, role="user", content="hi", sequence=0,
        ))
        session.add(ConversationMessage(
            conversation_id=c.id, role="assistant", content="hello", sequence=1,
        ))
        await session.commit()
        run_id = str(run.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/agent/runs/{run_id}/export",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["agent_run_id"] == run_id
    assert body["role"] == "DEV_BE"
    assert body["message_count"] == 2
    assert body["messages"][0]["content"] == "hi"


@pytest.mark.asyncio
async def test_export_run_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/agent/runs/{uuid.uuid4()}/export",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resume_run_only_from_pausable_status():
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
            f"/api/v1/agent/runs/{run_id}/resume",
            json={"approval_comment": "go"},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 400


# -------------------- Task 61: usage summary --------------------


@pytest.mark.asyncio
async def test_usage_summary_requires_org_for_non_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/agent/usage/summary",
            cookies={"access_token": _token(str(uuid.uuid4()), is_platform_admin=False)},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_usage_summary_platform_admin_works():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/agent/usage/summary?period=7d",
            cookies={"access_token": _token(str(uuid.uuid4()), is_platform_admin=True)},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["period"] == "7d"
    assert "total_tokens" in body
    assert "by_model" in body


@pytest.mark.asyncio
async def test_usage_summary_rejects_invalid_period():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/agent/usage/summary?period=99y",
            cookies={"access_token": _token(str(uuid.uuid4()), is_platform_admin=True)},
        )
    assert r.status_code == 422
