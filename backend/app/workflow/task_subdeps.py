"""Sub-task + task-dependency helpers (Sub-System C hardening).

- ``create_subtask(parent_id, ...)``: create a child of an existing task
- ``get_subtasks(parent_id)``: list all children of a task (1 level)
- ``get_descendants(root_id)``: recursive walk using SQL CTE
- ``add_dependency(blocker_id, blocked_id)``: create a dependency edge
  (raises if it would form a cycle)
- ``remove_dependency(blocker_id, blocked_id)``
- ``get_blockers(task_id)``: list tasks that block this one
- ``get_blocked(task_id)``: list tasks blocked by this one

Cycle detection uses Kahn's algorithm on the dependency graph.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskDependency


# ---------------------------------------------------------------------------
# Sub-tasks
# ---------------------------------------------------------------------------


async def create_subtask(
    session: AsyncSession,
    parent_id: UUID,
    *,
    title: str,
    org_id: str | None = None,
    assignee_id: str | None = None,
    description: str | None = None,
    priority: str = "medium",
    creator_id: str | None = None,
) -> Task:
    """Create a child task under ``parent_id``."""
    parent = await session.get(Task, parent_id)
    if parent is None:
        raise ValueError(f"Parent task {parent_id} not found")

    task = Task(
        org_id=org_id or parent.org_id,
        user_id=creator_id,
        assignee_id=assignee_id,
        title=title,
        description=description,
        priority=priority,
        source="manual",
        parent_id=parent_id,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_subtasks(session: AsyncSession, parent_id: UUID) -> list[Task]:
    """Return direct children of ``parent_id`` (one level only)."""
    stmt = select(Task).where(Task.parent_id == parent_id).order_by(Task.created_at)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_descendants(session: AsyncSession, root_id: UUID) -> list[Task]:
    """Walk the parent_id tree using a recursive CTE."""
    from sqlalchemy import text

    stmt = text("""
        WITH RECURSIVE descendants AS (
            SELECT * FROM tasks WHERE id = :root_id
            UNION
            SELECT t.* FROM tasks t
            INNER JOIN descendants d ON t.parent_id = d.id
        )
        SELECT id FROM descendants WHERE id != :root_id
        ORDER BY created_at
    """)
    result = await session.execute(stmt, {"root_id": str(root_id)})
    rows = result.fetchall()
    ids = [row[0] for row in rows]
    if not ids:
        return []
    stmt2 = select(Task).where(Task.id.in_(ids)).order_by(Task.created_at)
    result2 = await session.execute(stmt2)
    return list(result2.scalars().all())


async def would_create_subtask_cycle(
    session: AsyncSession, parent_id: UUID, new_child_id: UUID | None = None
) -> bool:
    """Returns True if assigning ``new_child_id`` as a child of ``parent_id``
    would create a cycle (i.e. parent_id is a descendant of new_child_id).
    """
    if new_child_id is None:
        return False
    descendants = await get_descendants(session, new_child_id)
    return any(t.id == parent_id for t in descendants)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def add_dependency(
    session: AsyncSession,
    blocker_id: UUID,
    blocked_id: UUID,
) -> TaskDependency:
    """Create a dependency edge. Raises ValueError on cycle / self-loop."""
    if blocker_id == blocked_id:
        raise ValueError("A task cannot block itself")

    blocker = await session.get(Task, blocker_id)
    blocked = await session.get(Task, blocked_id)
    if blocker is None:
        raise ValueError(f"Blocker task {blocker_id} not found")
    if blocked is None:
        raise ValueError(f"Blocked task {blocked_id} not found")

    existing = await session.execute(
        select(TaskDependency).where(
            TaskDependency.blocker_id == blocker_id,
            TaskDependency.blocked_id == blocked_id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Dependency {blocker_id} -> {blocked_id} already exists")

    if await _would_create_cycle(session, blocker_id, blocked_id):
        raise ValueError(f"Adding {blocker_id} -> {blocked_id} would create a cycle")

    dep = TaskDependency(
        id=uuid4(),
        blocker_id=blocker_id,
        blocked_id=blocked_id,
    )
    session.add(dep)
    await session.commit()
    return dep


async def _would_create_cycle(
    session: AsyncSession, new_blocker: UUID, new_blocked: UUID
) -> bool:
    """Use Kahn's algorithm to check if adding ``new_blocker -> new_blocked``
    creates a cycle in the dependency graph (excluding the new edge).
    """
    edges: list[tuple[UUID, UUID]] = []
    stmt = select(TaskDependency.blocker_id, TaskDependency.blocked_id)
    for row in (await session.execute(stmt)).all():
        edges.append((row[0], row[1]))
    edges.append((new_blocker, new_blocked))

    in_degree: dict[UUID, int] = defaultdict(int)
    adjacency: dict[UUID, list[UUID]] = defaultdict(list)
    nodes: set[UUID] = set()
    for blk, bld in edges:
        nodes.add(blk)
        nodes.add(bld)
        in_degree[bld] += 1
        adjacency[blk].append(bld)
    for n in nodes:
        in_degree.setdefault(n, 0)

    queue: deque[UUID] = deque(n for n, d in in_degree.items() if d == 0)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for nxt in adjacency[node]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    return visited != len(nodes)


async def remove_dependency(
    session: AsyncSession, blocker_id: UUID, blocked_id: UUID
) -> bool:
    stmt = delete(TaskDependency).where(
        TaskDependency.blocker_id == blocker_id,
        TaskDependency.blocked_id == blocked_id,
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount > 0


async def get_blockers(session: AsyncSession, task_id: UUID) -> list[Task]:
    """Tasks that must be done before ``task_id`` can start."""
    stmt = (
        select(Task)
        .join(TaskDependency, TaskDependency.blocker_id == Task.id)
        .where(TaskDependency.blocked_id == task_id)
        .order_by(Task.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_blocked_by(session: AsyncSession, task_id: UUID) -> list[Task]:
    """Tasks that ``task_id`` is blocking."""
    stmt = (
        select(Task)
        .join(TaskDependency, TaskDependency.blocked_id == Task.id)
        .where(TaskDependency.blocker_id == task_id)
        .order_by(Task.created_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def is_task_blocked(session: AsyncSession, task_id: UUID) -> bool:
    """True if any of the task's blockers are still open (not done/cancelled)."""
    blockers = await get_blockers(session, task_id)
    return any(b.status not in ("done", "cancelled") for b in blockers)