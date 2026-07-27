"""Workflow REST API tests."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session_maker
from app.main import app
from app.models.process import Process, ProcessDLQ, ProcessEvent, ProcessStep
from app.workflow.state import transition_process, transition_step


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


def _def() -> dict:
    return {
        "steps": [
            {"name": "a", "role": "ANL", "prompt": "p"},
            {"name": "b", "role": "DEV_BE", "prompt": "p"},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }


# -------------------- Create / list / get --------------------


@pytest.mark.asyncio
async def test_create_process_via_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/processes",
            json={"name": "sm-test", **_def()},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "sm-test"
    assert body["status"] == "draft"
    assert len(body["steps"]) == 2


@pytest.mark.asyncio
async def test_create_process_rejects_cycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/processes",
            json={
                "name": "cyclic",
                "steps": [
                    {"name": "a", "role": "ANL", "prompt": "p"},
                    {"name": "b", "role": "DEV_BE", "prompt": "p"},
                ],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
            },
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_process_unauthenticated():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/v1/processes", json={"name": "x", **_def()})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_processes():
    # Create one first
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/processes",
            json={"name": "list-test", **_def()},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
        r = await client.get(
            "/api/v1/processes",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_get_process_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            f"/api/v1/processes/{uuid.uuid4()}",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 404


# -------------------- Start / cancel / resume --------------------


@pytest.mark.asyncio
async def test_start_process_moves_to_queued_and_marks_roots():
    # Create a process via the API
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post(
            "/api/v1/processes",
            json={"name": "start-test", **_def()},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
        pid = create.json()["id"]

        r = await client.post(
            f"/api/v1/processes/{pid}/start",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    # Step 'a' is the root, should be queued; 'b' is dependent, should still be pending
    statuses = {s["step_name"]: s["status"] for s in body["steps"]}
    assert statuses["a"] == "queued"
    assert statuses["b"] == "pending"


@pytest.mark.asyncio
async def test_start_process_already_started_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post(
            "/api/v1/processes",
            json={"name": "start-twice", **_def()},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
        pid = create.json()["id"]
        await client.post(
            f"/api/v1/processes/{pid}/start",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
        r = await client.post(
            f"/api/v1/processes/{pid}/start",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_cancel_running_process():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post(
            "/api/v1/processes",
            json={"name": "cancel-test", **_def()},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
        pid = create.json()["id"]
        await client.post(
            f"/api/v1/processes/{pid}/start",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
        r = await client.post(
            f"/api/v1/processes/{pid}/cancel",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    # All steps should also be cancelled
    for s in body["steps"]:
        assert s["status"] == "cancelled"


@pytest.mark.asyncio
async def test_resume_paused_process():
    """Build a paused process manually, then resume it via the API."""
    # Create process + steps, transition to paused
    async with async_session_maker() as session:
        p = Process(
            name="resume-test",
            definition=_def(),
            status="paused",
            org_id=str(uuid.uuid4()),
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        a = ProcessStep(
            process_id=p.id, step_name="a", role="ANL",
            status="paused", prompt_template="p",
        )
        b = ProcessStep(
            process_id=p.id, step_name="b", role="DEV_BE",
            status="pending", prompt_template="p",
        )
        session.add_all([a, b])
        await session.commit()
        pid = str(p.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/processes/{pid}/resume",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running"
    # 'a' (paused) is requeued; 'b' is still pending
    statuses = {s["step_name"]: s["status"] for s in body["steps"]}
    assert statuses["a"] == "queued"


@pytest.mark.asyncio
async def test_resume_only_from_pausable_state():
    async with async_session_maker() as session:
        p = Process(
            name="resume-bad",
            definition=_def(),
            status="completed",
            org_id=str(uuid.uuid4()),
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        pid = str(p.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/processes/{pid}/resume",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 400


# -------------------- Events --------------------


@pytest.mark.asyncio
async def test_get_events_returns_event_log():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post(
            "/api/v1/processes",
            json={"name": "events-test", **_def()},
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
        pid = create.json()["id"]
        await client.post(
            f"/api/v1/processes/{pid}/start",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
        r = await client.get(
            f"/api/v1/processes/{pid}/events",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200
    events = r.json()
    types = {e["event_type"] for e in events}
    # process.created, process.queued, step.queued should all be present
    assert "process.created" in types
    assert "process.queued" in types
    assert "step.queued" in types


# -------------------- DLQ --------------------


@pytest.mark.asyncio
async def test_list_dlq_returns_unresolved():
    async with async_session_maker() as session:
        # Create a process so the DLQ FK is satisfied
        p = Process(
            name="dlq-test",
            definition=_def(),
            status="failed",
            org_id=str(uuid.uuid4()),
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        s = ProcessStep(
            process_id=p.id, step_name="a", role="ANL",
            status="failed", prompt_template="p", attempt=5,
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        dlq = ProcessDLQ(
            process_id=p.id, step_id=s.id,
            payload={"test": True}, reason="boom", retry_count=5,
        )
        session.add(dlq)
        await session.commit()
        await session.refresh(dlq)
        dlq_id = str(dlq.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/v1/process-dlq",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200
    body = r.json()
    ids = [it["id"] for it in body["items"]]
    assert dlq_id in ids


@pytest.mark.asyncio
async def test_replay_dlq_marks_resolved():
    async with async_session_maker() as session:
        p = Process(
            name="dlq-replay",
            definition=_def(),
            status="failed",
            org_id=str(uuid.uuid4()),
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        s = ProcessStep(
            process_id=p.id, step_name="a", role="ANL",
            status="failed", prompt_template="p", attempt=5,
        )
        session.add(s)
        await session.commit()
        await session.refresh(s)
        dlq = ProcessDLQ(
            process_id=p.id, step_id=s.id,
            payload={}, reason="x", retry_count=5,
        )
        session.add(dlq)
        await session.commit()
        await session.refresh(dlq)
        dlq_id = str(dlq.id)
        step_id = str(s.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/v1/process-dlq/{dlq_id}/replay",
            cookies={"access_token": _token(str(uuid.uuid4()))},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["replayed"] is True
    assert body["step_id"] == step_id

    # Verify the step is back in pending
    async with async_session_maker() as session:
        s = await session.get(ProcessStep, step_id)
        assert s.status == "pending"
        assert s.attempt == 0
