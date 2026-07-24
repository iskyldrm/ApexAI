import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt

from app.config import get_settings
from app.main import app


@pytest.mark.asyncio
async def test_get_current_user_from_jwt():
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": "user-123",
            "email": "test@example.com",
            "is_platform_admin": False,
            "orgs": [],
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/test-me",
            cookies={"access_token": token},
        )
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_get_current_user_no_token_returns_401():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/test-me")
    assert response.status_code == 401