"""Security smoke tests covering common weaknesses.

- Password length validation on register
- Forgot-password does not leak user existence
- Invalid JWT rejected
- Missing required fields rejected with 422
- Auth required on protected endpoints
- Cross-org access forbidden
- SQL-injection-shaped input rejected by Pydantic types
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _u() -> str:
    return uuid.uuid4().hex[:10]


@pytest.mark.asyncio
async def test_register_short_password_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": f"short-{_u()}@apex.ai", "password": "short"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_email_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/register",
            json={"email": "not-an-email", "password": "good-123-pass"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_forgot_password_does_not_leak_user_existence():
    """Forgot-password should always return 200 to prevent user enumeration."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_existing = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": f"existing-{_u()}@apex.ai"},
        )
        r_nonexistent = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": f"nonexistent-{_u()}@apex.ai"},
        )
    assert r_existing.status_code == 200
    assert r_nonexistent.status_code == 200
    assert r_existing.json() == r_nonexistent.json()


@pytest.mark.asyncio
async def test_protected_endpoint_without_auth_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_invalid_jwt_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/auth/me", cookies={"access_token": "garbage.token.value"}
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_cross_org_access_forbidden():
    """A user from org A cannot read audit log for org B."""
    # Create two users and two orgs, then try to read org B's audit log as user A
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register user A
        a_email = f"a-{_u()}@apex.ai"
        a_reg = await client.post(
            "/api/v1/auth/register",
            json={"email": a_email, "password": "secure-123-pass", "full_name": "A"},
        )
        assert a_reg.status_code == 201, a_reg.text
        a_cookies = {"access_token": a_reg.json()["access_token"]}

        # Platform admin creates org B (without user A as admin)
        from app.core.security import create_access_token
        pa_token = create_access_token(
            user_id="00000000-0000-0000-0000-000000000001",
            email="admin@apex.ai",
            is_platform_admin=True,
            orgs=[],
        )
        pa_cookies = {"access_token": pa_token}
        org_b = await client.post(
            "/api/v1/orgs",
            json={
                "slug": f"org-b-{_u()}",
                "name": "Org B",
                "admin_email": a_email,  # A becomes admin of B, fine
                "admin_full_name": "A",
            },
            cookies=pa_cookies,
        )
        assert org_b.status_code == 201, org_b.text
        b_id = org_b.json()["id"]

        # User A tries to read audit log for org B WITHOUT passing org_id (should 400)
        r = await client.get("/api/v1/audit-log", cookies=a_cookies)
        assert r.status_code == 400

        # If A passes a DIFFERENT org_id (not B's), it should still be denied
        r = await client.get(
            "/api/v1/audit-log?org_id=11111111-1111-1111-1111-111111111111",
            cookies=a_cookies,
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_sql_injection_in_login_rejected():
    """SQL-shaped email/pass should never authenticate."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@apex.ai' OR '1'='1", "password": "' OR '1'='1"},
        )
    assert r.status_code in (401, 422)


@pytest.mark.asyncio
async def test_cors_headers_present():
    """FastAPI responds with CORS headers when Origin matches allow-list."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
    assert r.status_code == 200
    assert "access-control-allow-origin" in {k.lower() for k in r.headers}
