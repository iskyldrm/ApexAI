"""API key + integration + settings + audit endpoint tests."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.core.security import hash_password
from app.db import async_session_maker
from app.main import app
from app.models.membership import OrgMembership
from app.models.org import Org
from app.models.user import User


def _token(
    user_id: str,
    is_platform_admin: bool = False,
    orgs: list[dict] | None = None,
) -> str:
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


async def _make_user() -> str:
    async with async_session_maker() as session:
        u = User(
            email=f"u-{uuid.uuid4().hex[:8]}@apex.ai",
            password_hash=hash_password("password123"),
            full_name="Tester",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return str(u.id)


async def _make_org_with_admin() -> tuple[str, str]:
    org_id, admin_id, _ = await _make_org_with_admin_full()
    return org_id, admin_id


async def _make_org_with_admin_full() -> tuple[str, str, str]:
    slug = f"org-{uuid.uuid4().hex[:8]}"
    admin_id = await _make_user()
    async with async_session_maker() as session:
        org = Org(slug=slug, name=f"Org {slug}", status="active")
        session.add(org)
        await session.flush()
        oid = str(org.id)
        session.add(
            OrgMembership(
                org_id=oid,
                user_id=admin_id,
                role="admin",
                status="active",
                joined_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return oid, admin_id, slug


@pytest.mark.asyncio
async def test_create_user_level_ai_key():
    user_id = await _make_user()
    token = _token(user_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/keys/ai",
            json={
                "provider": "openai",
                "label": "My OpenAI Key",
                "value": "sk-test-1234567890",
            },
            cookies={"access_token": token},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["provider"] == "openai"
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_create_org_level_ai_key_requires_admin():
    org_id, admin_id, _ = await _make_org_with_admin_full()
    non_admin_id = await _make_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Non-admin denied
        response = await client.post(
            f"/api/v1/keys/ai",
            json={
                "provider": "openai",
                "label": "Org Key",
                "value": "sk-test-1234567890",
                "org_id": org_id,
            },
            cookies={"access_token": _token(non_admin_id)},
        )
        assert response.status_code == 403
        # Admin allowed
        response = await client.post(
            "/api/v1/keys/ai",
            json={
                "provider": "anthropic",
                "label": "Org Anthropic Key",
                "value": "sk-ant-test-1234567890",
                "org_id": org_id,
            },
            cookies={"access_token": _token(admin_id)},
        )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_list_user_level_ai_keys():
    user_id = await _make_user()
    token = _token(user_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/keys/ai",
            json={"provider": "openai", "label": "K1", "value": "sk-test-aaaaaaaaa"},
            cookies={"access_token": token},
        )
        response = await client.get(
            "/api/v1/keys/ai", cookies={"access_token": token}
        )
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert any(k["label"] == "K1" for k in body)


@pytest.mark.asyncio
async def test_create_integration_credential():
    user_id = await _make_user()
    token = _token(user_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/keys/integrations",
            json={
                "integration_type": "github_pat",
                "label": "My GH",
                "value": {"token": "ghp_xxxxxxxxxxxxxxxxxxxx"},
            },
            cookies={"access_token": token},
        )
    assert response.status_code == 201, response.text
    assert response.json()["integration_type"] == "github_pat"


@pytest.mark.asyncio
async def test_setting_set_and_get_with_chain():
    """User-level setting wins over org-level."""
    org_id, admin_id, _ = await _make_org_with_admin_full()
    admin_token = _token(admin_id, orgs=[{"org_id": org_id, "teams": []}])

    # Set org-level
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.put(
            "/api/v1/settings/ai.default_provider",
            json={"scope": "org", "scope_id": org_id, "value": {"p": "openai"}},
            cookies={"access_token": admin_token},
        )
        assert r.status_code == 200, r.text
        # Get should resolve to org scope
        r = await client.get(
            "/api/v1/settings/ai.default_provider",
            cookies={"access_token": admin_token},
        )
    assert r.status_code == 200
    assert r.json()["scope"] == "org"
    assert r.json()["value"] == {"p": "openai"}


@pytest.mark.asyncio
async def test_setting_platform_requires_platform_admin():
    user_id = await _make_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/v1/settings/platform.flag",
            json={"scope": "platform", "value": {"on": True}},
            cookies={"access_token": _token(user_id)},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_platform_admin_sees_all():
    # Generate an audit event first
    from app.core.audit import audit

    await audit(
        action="test.audit_endpoint",
        actor_id="actor-1",
        actor_type="user",
        actor_email="actor@test.ai",
    )

    token = _token("platform-admin", is_platform_admin=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/audit-log?action=test.audit_endpoint",
            cookies={"access_token": token},
        )
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(it["action"] == "test.audit_endpoint" for it in items)


@pytest.mark.asyncio
async def test_audit_log_non_admin_requires_org_id():
    user_id = await _make_user()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/audit-log",
            cookies={"access_token": _token(user_id)},
        )
    assert response.status_code == 400  # missing org_id