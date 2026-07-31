"""Tests for sub-tasks + task dependencies (C.7-C.10)."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.db import async_session_maker
from app.models.task import Task, TaskDependency
from app.workflow.task_subdeps import (
    add_dependency,
    create_subtask,
    get_blocked_by,
    get_blockers,
    get_descendants,
    get_subtasks,
    is_task_blocked,
    remove_dependency,
)


def _make_task(**kwargs) -> Task:
    """Create an unsaved Task."""
    defaults = {
        "title": "Test task",
        "status": "todo",
        "priority": "medium",
        "source": "manual",
    }
    defaults.update(kwargs)
    return Task(**defaults)


async def _create(session, **kwargs) -> Task:
    t = _make_task(**kwargs)
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t


# -------------------- Sub-task tests --------------------


@pytest.mark.asyncio
async def test_create_subtask_sets_parent_id():
    async with async_session_maker() as session:
        parent = await _create(session, title="Parent")
        child = await create_subtask(
            session, parent.id, title="Child", priority="high"
        )
        assert child.parent_id == parent.id
        assert child.title == "Child"
        assert child.priority == "high"
        assert child.status == "todo"


@pytest.mark.asyncio
async def test_create_subtask_inherits_org_id_from_parent():
    async with async_session_maker() as session:
        parent = await _create(session, title="Parent", org_id="org-x")
        child = await create_subtask(session, parent.id, title="Child")
        assert child.org_id == "org-x"


@pytest.mark.asyncio
async def test_create_subtask_raises_for_unknown_parent():
    async with async_session_maker() as session:
        with pytest.raises(ValueError, match="not found"):
            await create_subtask(session, uuid4(), title="X")


@pytest.mark.asyncio
async def test_get_subtasks_returns_only_direct_children():
    async with async_session_maker() as session:
        parent = await _create(session, title="Parent")
        child1 = await create_subtask(session, parent.id, title="C1")
        child2 = await create_subtask(session, parent.id, title="C2")
        grandchild = await create_subtask(session, child1.id, title="GC")

        children = await get_subtasks(session, parent.id)
        names = {c.title for c in children}
        assert names == {"C1", "C2"}
        # Grandchild is NOT in direct children
        assert all(c.id != grandchild.id for c in children)


@pytest.mark.asyncio
async def test_get_descendants_walks_full_tree():
    async with async_session_maker() as session:
        root = await _create(session, title="Root")
        a = await create_subtask(session, root.id, title="A")
        b = await create_subtask(session, a.id, title="B")
        c = await create_subtask(session, b.id, title="C")

        descendants = await get_descendants(session, root.id)
        names = {t.title for t in descendants}
        assert names == {"A", "B", "C"}


@pytest.mark.asyncio
async def test_subtask_deletion_cascades():
    """Deleting the parent removes all sub-tasks."""
    from sqlalchemy import delete

    async with async_session_maker() as session:
        parent = await _create(session, title="Parent")
        child = await create_subtask(session, parent.id, title="Child")
        grandchild = await create_subtask(session, child.id, title="Grandchild")

        # Delete the parent
        await session.execute(delete(Task).where(Task.id == parent.id))
        await session.commit()

        # All three should be gone (FK ON DELETE CASCADE)
        remaining = await session.execute(
            delete(Task).where(Task.id.in_([parent.id, child.id, grandchild.id]))
        )
        await session.commit()
        assert remaining.rowcount == 0


# -------------------- Dependency tests --------------------


@pytest.mark.asyncio
async def test_add_dependency_creates_edge():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        dep = await add_dependency(session, a.id, b.id)
        assert dep.blocker_id == a.id
        assert dep.blocked_id == b.id


@pytest.mark.asyncio
async def test_add_dependency_rejects_self_loop():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        with pytest.raises(ValueError, match="itself"):
            await add_dependency(session, a.id, a.id)


@pytest.mark.asyncio
async def test_add_dependency_rejects_cycle():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        # A blocks B
        await add_dependency(session, a.id, b.id)
        # B → A would create cycle A → B → A
        with pytest.raises(ValueError, match="cycle"):
            await add_dependency(session, b.id, a.id)


@pytest.mark.asyncio
async def test_add_dependency_rejects_three_node_cycle():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        c = await _create(session, title="C")
        await add_dependency(session, a.id, b.id)
        await add_dependency(session, b.id, c.id)
        with pytest.raises(ValueError, match="cycle"):
            await add_dependency(session, c.id, a.id)


@pytest.mark.asyncio
async def test_add_dependency_rejects_duplicate():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        await add_dependency(session, a.id, b.id)
        with pytest.raises(ValueError, match="already exists"):
            await add_dependency(session, a.id, b.id)


@pytest.mark.asyncio
async def test_add_dependency_rejects_unknown_tasks():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        with pytest.raises(ValueError, match="not found"):
            await add_dependency(session, a.id, uuid4())
        with pytest.raises(ValueError, match="not found"):
            await add_dependency(session, uuid4(), a.id)


@pytest.mark.asyncio
async def test_remove_dependency():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        await add_dependency(session, a.id, b.id)
        removed = await remove_dependency(session, a.id, b.id)
        assert removed is True

        blockers = await get_blockers(session, b.id)
        assert blockers == []


@pytest.mark.asyncio
async def test_remove_dependency_returns_false_when_missing():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        removed = await remove_dependency(session, a.id, b.id)
        assert removed is False


@pytest.mark.asyncio
async def test_get_blockers_returns_blocking_tasks():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        c = await _create(session, title="C")
        # Both A and C block B
        await add_dependency(session, a.id, b.id)
        await add_dependency(session, c.id, b.id)

        blockers = await get_blockers(session, b.id)
        assert {b.id for b in blockers} == {a.id, c.id}


@pytest.mark.asyncio
async def test_get_blocked_by_returns_blocked_tasks():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        c = await _create(session, title="C")
        # A blocks both B and C
        await add_dependency(session, a.id, b.id)
        await add_dependency(session, a.id, c.id)

        blocked = await get_blocked_by(session, a.id)
        assert {t.id for t in blocked} == {b.id, c.id}


@pytest.mark.asyncio
async def test_is_task_blocked_when_blocker_open():
    async with async_session_maker() as session:
        a = await _create(session, title="A", status="todo")
        b = await _create(session, title="B")
        await add_dependency(session, a.id, b.id)

        assert await is_task_blocked(session, b.id) is True


@pytest.mark.asyncio
async def test_is_task_blocked_when_blocker_done():
    async with async_session_maker() as session:
        a = await _create(session, title="A", status="done")
        b = await _create(session, title="B")
        await add_dependency(session, a.id, b.id)

        assert await is_task_blocked(session, b.id) is False


@pytest.mark.asyncio
async def test_is_task_blocked_when_blocker_cancelled():
    async with async_session_maker() as session:
        a = await _create(session, title="A", status="cancelled")
        b = await _create(session, title="B")
        await add_dependency(session, a.id, b.id)

        assert await is_task_blocked(session, b.id) is False


@pytest.mark.asyncio
async def test_is_task_blocked_no_blockers():
    async with async_session_maker() as session:
        a = await _create(session, title="A")
        assert await is_task_blocked(session, a.id) is False


@pytest.mark.asyncio
async def test_dependency_cascade_on_task_delete():
    """Deleting a task removes its dependency edges."""
    from sqlalchemy import delete

    async with async_session_maker() as session:
        a = await _create(session, title="A")
        b = await _create(session, title="B")
        await add_dependency(session, a.id, b.id)

        # Delete A → both task + its dependencies should go away
        await session.execute(delete(Task).where(Task.id == a.id))
        await session.commit()

        remaining = await session.execute(
            delete(TaskDependency).where(TaskDependency.blocker_id == a.id)
        )
        await session.commit()
        assert remaining.rowcount == 0