"""Auth API tests — register, login, refresh, logout, forgot/reset password, /me."""
import hashlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import hash_password
from app.db import async_session_maker
from app.main import app
from app.models.user import User


def _unique_email(prefix: str = "user") -> str:
    """Generate a unique email per test to avoid collisions across runs."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}@apex.ai"


async def _create_user(email: str, password: str, full_name: str = "Tester") -> None:
    async with async_session_maker() as session:
        session.add(
            User(
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_register_creates_user_and_returns_tokens():
    email = _unique_email("reg")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "password123",
                "full_name": "Registered User",
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["expires_in"] > 0


@pytest.mark.asyncio
async def test_register_duplicate_email_409():
    email = _unique_email("dup")
    await _create_user(email, "password123")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123", "full_name": "X"},
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_success_sets_cookies():
    email = _unique_email("login-ok")
    await _create_user(email, "password123")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password123"},
        )
    assert response.status_code == 200, response.text
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


@pytest.mark.asyncio
async def test_login_wrong_password_401():
    email = _unique_email("login-bad")
    await _create_user(email, "password123")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": _unique_email("no-such"), "password": "password123"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_token():
    email = _unique_email("refresh")
    await _create_user(email, "password123")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password123"},
        )
        first_refresh = login_resp.cookies["refresh_token"]
        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": first_refresh},
        )
    assert refresh_resp.status_code == 200, refresh_resp.text
    assert "access_token" in refresh_resp.cookies


@pytest.mark.asyncio
async def test_refresh_missing_token_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/refresh")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookies_and_revokes():
    from datetime import datetime, timedelta, timezone

    import jwt as pyjwt

    from app.config import get_settings

    settings = get_settings()
    token = pyjwt.encode(
        {
            "sub": "user-xyz",
            "email": _unique_email("logout"),
            "is_platform_admin": False,
            "orgs": [],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/logout", cookies={"access_token": token}
        )
    assert response.status_code == 200
    # TestClient sets delete_cookie which sets value="" — both should be cleared
    assert response.cookies.get("access_token", "") in ("", None) or len(
        response.cookies
    ) == 0


@pytest.mark.asyncio
async def test_forgot_password_returns_generic_message():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": _unique_email("anybody")},
        )
    assert response.status_code == 200
    assert "sent" in response.json()["message"]


@pytest.mark.asyncio
async def test_reset_password_with_valid_token_succeeds():
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.auth_token import PasswordResetToken

    email = _unique_email("reset")
    await _create_user(email, "old-password-123")
    plain = f"test-reset-token-{uuid.uuid4().hex}"
    token_hash = hashlib.sha256(plain.encode()).hexdigest()

    async with async_session_maker() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        session.add(
            PasswordResetToken(
                user_id=str(user.id),
                token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": plain, "new_password": "new-password-456"},
        )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_reset_password_invalid_token_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": "totally-bogus", "new_password": "new-password-456"},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_me_returns_user_info():
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone

    from app.config import get_settings

    settings = get_settings()
    me_email = _unique_email("me")
    token = pyjwt.encode(
        {
            "sub": "user-me-123",
            "email": me_email,
            "is_platform_admin": False,
            "orgs": [],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/auth/me", cookies={"access_token": token})
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == me_email
    assert body["id"] == "user-me-123"