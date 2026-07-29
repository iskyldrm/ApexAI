"""Task + notification + activity-feed API tests."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import async_session_maker
from app.main import app
from app.models.task import Notification, Task
from app.workflow.task_service import TaskService


def _token(user_id: str) -> str:
    s = get_settings()
    return pyjwt.encode(
        {
            "sub": user_id,
            "email": "u@test.ai",
            "is_platform_admin": False,
            "orgs": [],
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        },
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )


@pytest.mark.asyncio
async def test_create_task_returns_201():
    async with async_session_maker() as session:
        svc = TaskService(session)
        await svc.create(title="setup env", user_id=str(uuid.uuid4()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/tasks",
            json={"title": "ship feature"},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "ship feature"
    assert body["status"] == "todo"


@pytest.mark.asyncio
async def test_list_tasks_filters_by_scope():
    user_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        await svc.create(title="mine-1", user_id=user_id)
        await svc.create(title="mine-2", user_id=user_id)
        await svc.create(title="other", user_id=str(uuid.uuid4()))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/tasks?scope=mine",
            cookies={"access_token": _token(user_id)},
        )
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()]
    assert "mine-1" in titles
    assert "mine-2" in titles
    assert "other" not in titles


@pytest.mark.asyncio
async def test_transition_task_changes_status():
    user_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=user_id)
        tid = str(task.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/tasks/{tid}/transition",
            json={"to": "in_progress"},
            cookies={"access_token": _token(user_id)},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_invalid_transition_returns_409():
    user_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=user_id)
        tid = str(task.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/tasks/{tid}/transition",
            json={"to": "done"},  # todo → done is not allowed
            cookies={"access_token": _token(user_id)},
        )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_add_comment_returns_201_and_appears_in_list():
    user_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=user_id)
        tid = str(task.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/tasks/{tid}/comments",
            json={"body": "first comment"},
            cookies={"access_token": _token(user_id)},
        )
    assert r.status_code == 201, r.text

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/tasks/{tid}/comments",
            cookies={"access_token": _token(user_id)},
        )
    assert r.status_code == 200
    bodies = [c["body"] for c in r.json()]
    assert "first comment" in bodies


@pytest.mark.asyncio
async def test_notification_assigned_appears_in_list():
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/tasks",
            json={"title": "review this", "assignee_id": user_b},
            cookies={"access_token": _token(user_a)},
        )
    assert r.status_code == 201

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/notifications",
            cookies={"access_token": _token(user_b)},
        )
    assert r.status_code == 200
    notifs = r.json()
    assert any(n["kind"] == "task.assigned" for n in notifs)


@pytest.mark.asyncio
async def test_mark_all_read_clears_unread():
    user_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    # Create a few notifications
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            await client.post(
                "/api/v1/tasks",
                json={"title": "x", "assignee_id": user_id},
                cookies={"access_token": _token(str(uuid.uuid4()))},
            )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/notifications?unread_only=true",
            cookies={"access_token": _token(user_id)},
        )
    unread = r.json()
    assert len(unread) >= 3

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/notifications/read-all",
            cookies={"access_token": _token(user_id)},
        )
    assert r.status_code == 200
    assert r.json()["marked_read"] >= 3


@pytest.mark.asyncio
async def test_activity_feed_returns_recent_events():
    user_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        await svc.create(title="activity-test", user_id=user_id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/activity-feed",
            cookies={"access_token": _token(user_id)},
        )
    assert r.status_code == 200
    feed = r.json()
    # Should have at least one task.* entry
    sources = {e["source"] for e in feed}
    assert "task" in sources