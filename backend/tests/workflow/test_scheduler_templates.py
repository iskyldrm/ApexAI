"""Tests for cron scheduling + workflow templates (B.5-B.12)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.db import async_session_maker
from app.models.process import Process, ScheduledProcess, WorkflowTemplate
from app.workflow.scheduler import (
    create_schedule,
    delete_schedule,
    get_scheduler,
    list_schedules,
    set_schedule_enabled,
    shutdown_scheduler,
)
from app.workflow.templates import (
    SEED_TEMPLATES,
    clone_template,
    list_templates,
    seed_templates,
)


@pytest.fixture(autouse=True)
def _reset_scheduler():
    """Reset APScheduler state between tests."""
    shutdown_scheduler()
    yield
    shutdown_scheduler()


# -------------------- Scheduler tests --------------------


@pytest.mark.asyncio
async def test_create_schedule_persists_row():
    """create_schedule adds a ScheduledProcess row + registers an APScheduler job."""
    from sqlalchemy import delete

    async with async_session_maker() as session:
        # Need a Process row to satisfy the FK
        proc = Process(
            id=uuid4(),
            name="test-sched",
            description="",
            definition={"nodes": [], "edges": []},
            status="draft",
        )
        session.add(proc)
        await session.commit()

        sched = await create_schedule(
            session,
            process_id=proc.id,
            cron_expr="0 9 * * 1",  # Mondays at 9
            org_id=None,
        )
        assert sched.id is not None
        assert sched.cron_expr == "0 9 * * 1"
        assert sched.enabled is True

        # Verify APScheduler registered it
        scheduler = get_scheduler()
        if scheduler.running:
            job = scheduler.get_job(f"sched-{sched.id}")
            assert job is not None

        # Cleanup
        await session.execute(delete(ScheduledProcess).where(ScheduledProcess.id == sched.id))
        await session.execute(delete(Process).where(Process.id == proc.id))
        await session.commit()


@pytest.mark.asyncio
async def test_create_schedule_handles_bad_cron():
    """A malformed cron expression logs a warning but still persists the row."""
    from sqlalchemy import delete

    async with async_session_maker() as session:
        proc = Process(
            id=uuid4(),
            name="test-bad-cron",
            description="",
            definition={"nodes": [], "edges": []},
            status="draft",
        )
        session.add(proc)
        await session.commit()

        # Should not raise — APScheduler logs and skips
        sched = await create_schedule(
            session,
            process_id=proc.id,
            cron_expr="not a valid cron",
            org_id=None,
        )
        assert sched.id is not None

        # Cleanup
        await session.execute(delete(ScheduledProcess).where(ScheduledProcess.id == sched.id))
        await session.execute(delete(Process).where(Process.id == proc.id))
        await session.commit()


@pytest.mark.asyncio
async def test_set_schedule_enabled_toggles():
    from sqlalchemy import delete

    async with async_session_maker() as session:
        proc = Process(
            id=uuid4(),
            name="toggle-test",
            description="",
            definition={"nodes": [], "edges": []},
            status="draft",
        )
        session.add(proc)
        await session.commit()

        sched = await create_schedule(
            session,
            process_id=proc.id,
            cron_expr="*/5 * * * *",
        )
        sched_id = sched.id

        # Disable
        sched = await set_schedule_enabled(session, sched_id, False)
        assert sched.enabled is False

        # Re-enable
        sched = await set_schedule_enabled(session, sched_id, True)
        assert sched.enabled is True

        # Cleanup
        await session.execute(delete(ScheduledProcess).where(ScheduledProcess.id == sched_id))
        await session.execute(delete(Process).where(Process.id == proc.id))
        await session.commit()


@pytest.mark.asyncio
async def test_delete_schedule_removes_row():
    from sqlalchemy import delete

    async with async_session_maker() as session:
        proc = Process(
            id=uuid4(),
            name="delete-test",
            description="",
            definition={"nodes": [], "edges": []},
            status="draft",
        )
        session.add(proc)
        await session.commit()

        sched = await create_schedule(session, process_id=proc.id, cron_expr="0 12 * * *")
        sched_id = sched.id

        deleted = await delete_schedule(session, sched_id)
        assert deleted is True

        # Verify gone
        remaining = await list_schedules(session)
        assert all(s.id != sched_id for s in remaining)

        # Cleanup just in case
        await session.execute(delete(Process).where(Process.id == proc.id))
        await session.commit()


@pytest.mark.asyncio
async def test_list_schedules_filters_by_org():
    from sqlalchemy import delete

    async with async_session_maker() as session:
        # Two schedules in two orgs
        org_a = f"org-a-{uuid4().hex[:6]}"
        org_b = f"org-b-{uuid4().hex[:6]}"
        proc = Process(
            id=uuid4(),
            name="list-test",
            description="",
            definition={"nodes": [], "edges": []},
            status="draft",
        )
        session.add(proc)
        await session.commit()

        s_a = await create_schedule(session, process_id=proc.id, cron_expr="0 1 * * *", org_id=org_a)
        s_b = await create_schedule(session, process_id=proc.id, cron_expr="0 2 * * *", org_id=org_b)

        a_rows = await list_schedules(session, org_id=org_a)
        b_rows = await list_schedules(session, org_id=org_b)
        all_rows = await list_schedules(session)

        assert any(s.id == s_a.id for s in a_rows)
        assert all(s.id != s_b.id for s in a_rows)
        assert any(s.id == s_b.id for s in b_rows)
        assert any(s.id == s_a.id for s in all_rows)

        await session.execute(delete(ScheduledProcess))
        await session.execute(delete(Process))
        await session.commit()


# -------------------- Template tests --------------------


@pytest.mark.asyncio
async def test_seed_templates_inserts_defaults():
    from sqlalchemy import delete

    async with async_session_maker() as session:
        # Clean any existing seeded templates (test isolation)
        await session.execute(delete(WorkflowTemplate))

        n = await seed_templates(session)
        assert n == len(SEED_TEMPLATES)

        # Re-running should be idempotent
        n2 = await seed_templates(session)
        assert n2 == 0

        # Verify names
        rows = await list_templates(session)
        names = {r.name for r in rows}
        assert "bug-fix-pipeline" in names
        assert "code-review" in names
        assert "doc-update" in names


@pytest.mark.asyncio
async def test_clone_template_creates_process():
    from sqlalchemy import delete

    async with async_session_maker() as session:
        await session.execute(delete(WorkflowTemplate))
        await seed_templates(session)
        templates = await list_templates(session)
        bug_fix = next(t for t in templates if t.name == "bug-fix-pipeline")

        process = await clone_template(
            session,
            bug_fix.id,
            org_id="test-org",
            user_id="test-user",
            name="my-bug-fix",
        )
        assert process.id is not None
        assert process.name == "my-bug-fix"
        assert process.org_id == "test-org"
        assert process.status == "draft"
        assert process.definition == bug_fix.definition

        # Cleanup
        await session.execute(delete(Process).where(Process.id == process.id))
        await session.execute(delete(WorkflowTemplate))
        await session.commit()


@pytest.mark.asyncio
async def test_clone_template_raises_for_unknown_id():
    from sqlalchemy import delete

    async with async_session_maker() as session:
        await session.execute(delete(WorkflowTemplate))
        with pytest.raises(ValueError):
            await clone_template(session, uuid4(), org_id=None, user_id=None)


@pytest.mark.asyncio
async def test_list_templates_filters_by_category():
    from sqlalchemy import delete

    async with async_session_maker() as session:
        await session.execute(delete(WorkflowTemplate))
        await seed_templates(session)

        bug_fix = await list_templates(session, category="bug-fix")
        assert len(bug_fix) >= 1
        assert all(t.category == "bug-fix" for t in bug_fix)


def test_seed_templates_have_valid_structure():
    """Every seed template has nodes + edges; nodes referenced by edges exist."""
    for tpl in SEED_TEMPLATES:
        assert "nodes" in tpl["definition"]
        assert "edges" in tpl["definition"]
        node_ids = {n["id"] for n in tpl["definition"]["nodes"]}
        for edge in tpl["definition"]["edges"]:
            assert edge["from"] in node_ids, (
                f"{tpl['name']}: edge.from={edge['from']!r} not in {node_ids}"
            )
            assert edge["to"] in node_ids, (
                f"{tpl['name']}: edge.to={edge['to']!r} not in {node_ids}"
            )