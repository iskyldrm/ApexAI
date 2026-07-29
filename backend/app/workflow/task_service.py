"""TaskService — CRUD + status transitions + linking + notifications.

Pure-Python helper (no FastAPI coupling). Used by:
- REST API endpoints (C)
- Agent runtime (A) — auto-create tasks from long-running runs
- Workflow executor (B) — auto-create tasks from completed processes
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.models.notification_helpers import create_notification
from app.models.task import Notification, Task, TaskComment


logger = logging.getLogger(__name__)


# Allowed status transitions
ALLOWED_TASK_TRANSITIONS: dict[str, set[str]] = {
    "todo": {"in_progress", "cancelled"},
    "in_progress": {"review", "todo", "cancelled"},
    "review": {"in_progress", "done", "cancelled"},
    "done": set(),  # terminal
    "cancelled": {"todo"},  # can re-open
}

VALID_STATUSES = {"todo", "in_progress", "review", "done", "cancelled"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
VALID_SOURCES = {"manual", "agent_run", "process"}


class InvalidTransition(ValueError):
    """Raised when a task status transition is not allowed."""


class TaskService:
    """Service for creating, updating, transitioning, and notifying on tasks."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------- Create ----------------

    async def create(
        self,
        *,
        title: str,
        org_id: str | None = None,
        user_id: str | None = None,
        assignee_id: str | None = None,
        description: str | None = None,
        priority: str = "medium",
        source: str = "manual",
        source_id: UUID | None = None,
        due_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Task:
        """Create a new task and emit a notification if assigned."""
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {priority}")
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source: {source}")

        task = Task(
            title=title,
            org_id=org_id,
            user_id=user_id,
            assignee_id=assignee_id,
            description=description,
            priority=priority,
            source=source,
            source_id=source_id,
            due_at=due_at,
            meta=meta or {},
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)

        await audit(
            action="task.created",
            actor_id=user_id or "system",
            actor_type="user",
            actor_email=None,
            target_type="task",
            target_id=str(task.id),
            org_id=org_id,
            metadata={"title": title, "priority": priority, "source": source},
        )

        if assignee_id and assignee_id != user_id:
            await create_notification(
                self.session,
                user_id=assignee_id,
                org_id=org_id,
                kind="task.assigned",
                title=f"You were assigned: {title}",
                body=description[:200] if description else None,
                link=f"/tasks/{task.id}",
            )
            await self.session.commit()

        return task

    # ---------------- Read ----------------

    async def get(self, task_id: UUID) -> Task | None:
        return await self.session.get(Task, str(task_id))

    async def list(
        self,
        *,
        org_id: str | None = None,
        assignee_id: str | None = None,
        status: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[Task]:
        query = select(Task).order_by(Task.created_at.desc()).limit(limit)
        if org_id:
            query = query.where(Task.org_id == org_id)
        if assignee_id:
            query = query.where(Task.assignee_id == assignee_id)
        if status:
            query = query.where(Task.status == status)
        if source:
            query = query.where(Task.source == source)
        result = await self.session.execute(query)
        return list(result.scalars())

    async def list_for_user(
        self, user_id: str, statuses: list[str] | None = None, limit: int = 50
    ) -> list[Task]:
        """Tasks the user owns OR is assigned to."""
        from sqlalchemy import or_

        query = (
            select(Task)
            .where(or_(Task.user_id == user_id, Task.assignee_id == user_id))
            .order_by(Task.created_at.desc())
            .limit(limit)
        )
        if statuses:
            query = query.where(Task.status.in_(statuses))
        result = await self.session.execute(query)
        return list(result.scalars())

    # ---------------- Update ----------------

    async def update(
        self,
        task_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        assignee_id: str | None = None,
        priority: str | None = None,
        due_at: datetime | None = None,
        actor_id: str | None = None,
    ) -> Task:
        """Patch task fields. Use transition_status() for status changes."""
        task = await self.session.get(Task, str(task_id))
        if not task:
            raise ValueError(f"Task {task_id} not found")

        changes: dict[str, Any] = {}
        if title is not None:
            task.title = title
            changes["title"] = title
        if description is not None:
            task.description = description
            changes["description"] = description
        if assignee_id is not None and assignee_id != task.assignee_id:
            task.assignee_id = assignee_id
            changes["assignee_id"] = assignee_id
            # Notify new assignee
            if assignee_id and assignee_id != actor_id:
                await create_notification(
                    self.session,
                    user_id=assignee_id,
                    org_id=task.org_id,
                    kind="task.assigned",
                    title=f"You were assigned: {task.title}",
                    link=f"/tasks/{task.id}",
                )
        if priority is not None:
            if priority not in VALID_PRIORITIES:
                raise ValueError(f"Invalid priority: {priority}")
            task.priority = priority
            changes["priority"] = priority
        if due_at is not None:
            task.due_at = due_at
            changes["due_at"] = due_at.isoformat()

        await self.session.commit()
        await self.session.refresh(task)

        if changes:
            await audit(
                action="task.updated",
                actor_id=actor_id or "system",
                actor_type="user",
                target_type="task",
                target_id=str(task.id),
                org_id=task.org_id,
                metadata={"changes": changes},
            )
        return task

    # ---------------- Transition ----------------

    async def transition_status(
        self,
        task_id: UUID,
        to_status: str,
        actor_id: str | None = None,
    ) -> Task:
        """Change task status with validation. Emits notification if done."""
        if to_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {to_status}")

        task = await self.session.get(Task, str(task_id))
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if to_status == task.status:
            return task  # no-op

        if to_status not in ALLOWED_TASK_TRANSITIONS.get(task.status, set()):
            raise InvalidTransition(
                f"Cannot move task {task_id} from {task.status!r} → {to_status!r}"
            )

        old = task.status
        task.status = to_status
        if to_status == "done":
            task.completed_at = datetime.utcnow()
        elif to_status == "todo" and task.completed_at:
            # Re-opening — clear completed_at
            task.completed_at = None

        await self.session.commit()
        await self.session.refresh(task)

        await audit(
            action=f"task.{to_status}",
            actor_id=actor_id or "system",
            actor_type="user",
            target_type="task",
            target_id=str(task.id),
            org_id=task.org_id,
            metadata={"from": old, "to": to_status, "title": task.title},
        )

        # Notify watchers: assignee + creator
        for uid in {task.assignee_id, task.user_id}:
            if uid and uid != actor_id:
                await create_notification(
                    self.session,
                    user_id=uid,
                    org_id=task.org_id,
                    kind=f"task.{to_status}",
                    title=f"Task {to_status}: {task.title}",
                    link=f"/tasks/{task.id}",
                )
        await self.session.commit()
        return task

    # ---------------- Comments ----------------

    async def add_comment(
        self,
        task_id: UUID,
        body: str,
        author_id: str | None = None,
        author_type: str = "user",
    ) -> TaskComment:
        task = await self.session.get(Task, str(task_id))
        if not task:
            raise ValueError(f"Task {task_id} not found")

        comment = TaskComment(
            task_id=task_id,
            author_id=author_id,
            author_type=author_type,
            body=body,
        )
        self.session.add(comment)
        await self.session.commit()
        await self.session.refresh(comment)

        # Notify watchers
        for uid in {task.assignee_id, task.user_id}:
            if uid and uid != author_id:
                await create_notification(
                    self.session,
                    user_id=uid,
                    org_id=task.org_id,
                    kind="task.commented",
                    title=f"New comment on: {task.title}",
                    body=body[:200],
                    link=f"/tasks/{task.id}",
                )
        await self.session.commit()
        return comment

    async def list_comments(self, task_id: UUID) -> list[TaskComment]:
        result = await self.session.execute(
            select(TaskComment)
            .where(TaskComment.task_id == task_id)
            .order_by(TaskComment.created_at)
        )
        return list(result.scalars())

    # ---------------- Auto-create helpers (for A + B) ----------------

    async def create_from_agent_run(
        self,
        *,
        agent_run_id: UUID,
        title: str,
        summary: str | None = None,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> Task:
        """Convenience: a long-running agent run produced something worth tracking."""
        return await self.create(
            title=title,
            description=summary,
            org_id=org_id,
            user_id=user_id,
            priority="medium",
            source="agent_run",
            source_id=agent_run_id,
        )

    async def create_from_process(
        self,
        *,
        process_id: UUID,
        title: str,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> Task:
        """A completed process needs follow-up."""
        return await self.create(
            title=title,
            org_id=org_id,
            user_id=user_id,
            priority="medium",
            source="process",
            source_id=process_id,
        )