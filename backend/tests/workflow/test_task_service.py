"""TaskService tests — CRUD + transitions + notifications."""
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.db import async_session_maker
from app.models.task import Notification, Task
from app.workflow.task_service import (
    InvalidTransition,
    TaskService,
)


@pytest.fixture
def session():
    from app.db import async_session_maker
    return async_session_maker()


@pytest.mark.asyncio
async def test_create_task_basic():
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(
            title="Fix login bug",
            user_id=str(uuid.uuid4()),
        )
        assert task.id is not None
        assert task.status == "todo"
        assert task.priority == "medium"


@pytest.mark.asyncio
async def test_create_with_assignee_creates_notification():
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(
            title="Review PR",
            user_id=user_a,
            assignee_id=user_b,
        )
        # user_b should have an unread notification
        result = await session.execute(
            select(Notification).where(Notification.user_id == user_b)
        )
        notifs = list(result.scalars())
        assert len(notifs) == 1
        assert notifs[0].kind == "task.assigned"


@pytest.mark.asyncio
async def test_transition_todo_to_in_progress():
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=str(uuid.uuid4()))
        updated = await svc.transition_status(task.id, "in_progress")
        assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_transition_in_progress_to_review_to_done():
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=str(uuid.uuid4()))
        await svc.transition_status(task.id, "in_progress")
        await svc.transition_status(task.id, "review")
        updated = await svc.transition_status(task.id, "done")
        assert updated.status == "done"
        assert updated.completed_at is not None


@pytest.mark.asyncio
async def test_invalid_transition_raises():
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=str(uuid.uuid4()))
        # todo → done is not allowed
        with pytest.raises(InvalidTransition):
            await svc.transition_status(task.id, "done")


@pytest.mark.asyncio
async def test_done_is_terminal():
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=str(uuid.uuid4()))
        await svc.transition_status(task.id, "in_progress")
        await svc.transition_status(task.id, "review")
        await svc.transition_status(task.id, "done")
        with pytest.raises(InvalidTransition):
            await svc.transition_status(task.id, "in_progress")


@pytest.mark.asyncio
async def test_cancelled_can_reopen_to_todo():
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=str(uuid.uuid4()))
        await svc.transition_status(task.id, "cancelled")
        # Re-open
        reopened = await svc.transition_status(task.id, "todo")
        assert reopened.status == "todo"


@pytest.mark.asyncio
async def test_invalid_priority_raises():
    async with async_session_maker() as session:
        svc = TaskService(session)
        with pytest.raises(ValueError):
            await svc.create(title="x", priority="super-urgent", user_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_update_assignee_creates_notification():
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    user_c = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=user_a, assignee_id=user_b)
        # Reassign to user_c
        await svc.update(task.id, assignee_id=user_c, actor_id=user_a)
        result = await session.execute(
            select(Notification).where(Notification.user_id == user_c)
        )
        assert len(list(result.scalars())) == 1


@pytest.mark.asyncio
async def test_add_comment_creates_notification():
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        task = await svc.create(title="x", user_id=user_a, assignee_id=user_b)
        await svc.add_comment(task.id, "looks good!", author_id=user_a)
        comments = await svc.list_comments(task.id)
        assert len(comments) == 1
        assert comments[0].body == "looks good!"


@pytest.mark.asyncio
async def test_list_filters_by_org_and_status():
    user_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        svc = TaskService(session)
        a = await svc.create(title="a", user_id=user_id)
        b = await svc.create(title="b", user_id=user_id)
        await svc.create(title="c", user_id=user_id)
        # Move one to in_progress
        await svc.transition_status(a.id, "in_progress")
        ours = await svc.list_for_user(user_id)
        assert len(ours) == 3
        in_progress = await svc.list_for_user(user_id, statuses=["in_progress"])
        assert len(in_progress) == 1


@pytest.mark.asyncio
async def test_create_from_agent_run_links_source():
    async with async_session_maker() as session:
        svc = TaskService(session)
        agent_run_id = uuid.uuid4()
        task = await svc.create_from_agent_run(
            agent_run_id=agent_run_id,
            title="Fix the bug",
            summary="Null pointer in auth.py",
        )
        assert task.source == "agent_run"
        assert str(task.source_id) == str(agent_run_id)