"""Org / Team / Membership / Invitation API tests."""
import uuid

import jwt as pyjwt
import pytest
from datetime import datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.core.security import hash_password
from app.db import async_session_maker
from app.main import app
from app.models.membership import OrgMembership
from app.models.user import User


def _platform_admin_token() -> str:
    settings = get_settings()
    return pyjwt.encode(
        {
            "sub": "platform-admin-1",
            "email": "platform@apex.ai",
            "is_platform_admin": True,
            "orgs": [],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _user_token(user_id: str) -> str:
    settings = get_settings()
    return pyjwt.encode(
        {
            "sub": user_id,
            "email": "user@test.ai",
            "is_platform_admin": False,
            "orgs": [],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


async def _make_user(email: str | None = None) -> str:
    """Create a user and return its UUID string."""
    email = email or f"u-{uuid.uuid4().hex[:8]}@apex.ai"
    async with async_session_maker() as session:
        u = User(
            email=email,
            password_hash=hash_password("password123"),
            full_name="Test User",
        )
        session.add(u)
        await session.commit()
        await session.refresh(u)
        return str(u.id), u.email


async def _make_org_with_admin(slug: str | None = None) -> tuple[str, str, str]:
    """Create an org + admin user + admin membership. Returns (org_id, admin_user_id, admin_email)."""
    from app.models.org import Org

    slug = slug or f"org-{uuid.uuid4().hex[:8]}"
    admin_id, admin_email = await _make_user(f"admin-{uuid.uuid4().hex[:8]}@apex.ai")
    async with async_session_maker() as session:
        org = Org(slug=slug, name=f"Org {slug}", status="active")
        session.add(org)
        await session.flush()
        org_id = str(org.id)
        session.add(
            OrgMembership(
                org_id=org_id,
                user_id=admin_id,
                role="admin",
                status="active",
                joined_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return org_id, admin_id, admin_email


@pytest.mark.asyncio
async def test_platform_admin_create_org():
    token = _platform_admin_token()
    admin_email = f"newadmin-{uuid.uuid4().hex[:8]}@apex.ai"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/orgs",
            json={
                "slug": f"acme-{uuid.uuid4().hex[:6]}",
                "name": "Acme Corp",
                "admin_email": admin_email,
                "admin_full_name": "Acme Admin",
            },
            cookies={"access_token": token},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["slug"].startswith("acme-")
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_non_admin_cannot_create_org():
    user_id, _ = await _make_user()
    token = _user_token(user_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/orgs",
            json={
                "slug": "forbidden",
                "name": "Forbidden Org",
                "admin_email": "x@x.ai",
                "admin_full_name": "X",
            },
            cookies={"access_token": token},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_list_orgs():
    token = _platform_admin_token()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/orgs", cookies={"access_token": token}
        )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_org_admin_creates_team():
    org_id, admin_id, _ = await _make_org_with_admin()
    token = _user_token(admin_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/orgs/{org_id}/teams",
            json={"name": "Engineering", "slug": f"eng-{uuid.uuid4().hex[:6]}"},
            cookies={"access_token": token},
        )
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Engineering"


@pytest.mark.asyncio
async def test_non_member_cannot_create_team():
    org_id, _, _ = await _make_org_with_admin()
    other_user_id, _ = await _make_user()
    token = _user_token(other_user_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/orgs/{org_id}/teams",
            json={"name": "Sneaky", "slug": "sneaky"},
            cookies={"access_token": token},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_org_admin_list_teams():
    org_id, admin_id, _ = await _make_org_with_admin()
    token = _user_token(admin_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/orgs/{org_id}/teams", cookies={"access_token": token}
        )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_invitation_lifecycle():
    """Admin creates invite, accept endpoint consumes it, user becomes member."""
    from app.api.v1.orgs import _require_org_admin  # noqa: F401  # ensure import works

    org_id, admin_id, _ = await _make_org_with_admin()
    invite_email = f"invitee-{uuid.uuid4().hex[:8]}@apex.ai"
    token = _user_token(admin_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create invitation
        create_resp = await client.post(
            f"/api/v1/invitations/orgs/{org_id}",
            json={"email": invite_email, "role": "developer", "team_ids": []},
            cookies={"access_token": token},
        )
        assert create_resp.status_code == 201, create_resp.text

        # We can't get the plain token from the response (only metadata),
        # so simulate by reading it back from the email log.
        import json as _json

        with open("/tmp/apexai_emails.log") as f:
            last_email = None
            for line in f:
                record = _json.loads(line)
                if record["to"] == invite_email:
                    last_email = record
        assert last_email is not None
        # Token is in the URL query string
        plain = last_email["body"].split("token=")[1].strip()
        accept_resp = await client.post(
            "/api/v1/invitations/accept",
            json={
                "token": plain,
                "password": "new-password-123",
                "full_name": "Invitee User",
            },
        )
    assert accept_resp.status_code == 200, accept_resp.text


@pytest.mark.asyncio
async def test_list_org_invitations_requires_admin():
    org_id, _, _ = await _make_org_with_admin()
    other_user_id, _ = await _make_user()
    token = _user_token(other_user_id)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/invitations/orgs/{org_id}",
            cookies={"access_token": token},
        )
    assert response.status_code == 403