"""End-to-end smoke test: full happy-path flow across the entire API.

Walks: register → /me → create org (registered user becomes admin) →
create team → create AI key → set org setting → read resolved setting →
view audit log. Run with: cd backend && uv run pytest tests/api/test_e2e.py -v -s
"""
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _u() -> str:
    return uuid.uuid4().hex[:10]


async def _post(client, path, body, cookies=None):
    r = await client.post(path, json=body, cookies=cookies or {})
    assert r.status_code < 400, f"POST {path} → {r.status_code}: {r.text}"
    return r.json() if r.status_code != 204 else {}


async def _get(client, path, cookies=None):
    r = await client.get(path, cookies=cookies or {})
    assert r.status_code < 400, f"GET {path} → {r.status_code}: {r.text}"
    return r.json() if r.status_code != 204 else {}


async def _put(client, path, body, cookies):
    r = await client.put(path, json=body, cookies=cookies)
    assert r.status_code < 400, f"PUT {path} → {r.status_code}: {r.text}"
    return r.json() if r.status_code != 204 else {}


async def _delete(client, path, cookies=None):
    r = await client.delete(path, cookies=cookies or {})
    assert r.status_code < 400, f"DELETE {path} → {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_e2e_happy_path():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register a regular user
        email = f"e2e-{_u()}@apex.ai"
        reg = await _post(client, "/api/v1/auth/register", {
            "email": email, "password": "secure-123-pass", "full_name": "E2E"
        })
        user_cookies = {"access_token": reg["access_token"]}

        # 2. /me
        me = await _get(client, "/api/v1/auth/me", user_cookies)
        assert me["email"] == email

        # 3. Login again (logout -> login round-trip)
        await _post(client, "/api/v1/auth/logout", {}, user_cookies)
        login = await _post(client, "/api/v1/auth/login",
                            {"email": email, "password": "secure-123-pass"})
        user_cookies = {"access_token": login["access_token"]}

        # 4. Wait — only platform admin can create orgs. Get a platform admin token.
        from app.core.security import create_access_token
        pa_token = create_access_token(
            user_id="00000000-0000-0000-0000-000000000001",
            email="admin@apex.ai",
            is_platform_admin=True,
            orgs=[],
        )
        pa_cookies = {"access_token": pa_token}

        # 5. Create org with the registered user as admin
        org = await _post(client, "/api/v1/orgs", {
            "slug": f"e2e-{_u()}", "name": "E2E Org",
            "admin_email": email, "admin_full_name": "E2E",
        }, pa_cookies)
        org_id = org["id"]

        # 6. The registered user is now an org admin — refresh JWT to load orgs
        login2 = await _post(client, "/api/v1/auth/login",
                             {"email": email, "password": "secure-123-pass"})
        admin_cookies = {"access_token": login2["access_token"]}

        # 7. Create team as the org admin
        team = await _post(client, f"/api/v1/orgs/{org_id}/teams",
                           {"slug": f"team-{_u()}", "name": "Engineering"}, admin_cookies)
        assert team["org_id"] == org_id

        # 8. Create AI key on the org
        ai_key = await _post(client, "/api/v1/keys/ai",
                             {"provider": "openai", "label": "Org Key",
                              "value": "sk-test-e2e", "org_id": org_id}, admin_cookies)
        assert ai_key["provider"] == "openai"

        # 9. Set and read org scope setting
        await _put(client, "/api/v1/settings/ai.default_model",
                   {"scope": "org", "scope_id": org_id,
                    "value": {"model": "gpt-4o"}}, admin_cookies)
        s = await _get(client, "/api/v1/settings/ai.default_model", admin_cookies)
        assert s["scope"] == "org"
        assert s["value"] == {"model": "gpt-4o"}

        # 10. Audit log (admin can read their org's events)
        log = await _get(client, f"/api/v1/audit-log?org_id={org_id}", admin_cookies)
        assert "items" in log
        actions = {it["action"] for it in log["items"]}
        # org-scoped events should be present
        assert "org.created" in actions, f"missing org.created in {actions}"
        assert "api_key.created" in actions, f"missing api_key.created in {actions}"
