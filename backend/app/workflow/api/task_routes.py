"""Task + notification + activity-feed REST API.

POST   /tasks                       → create
GET    /tasks                       → list (filters: status, assignee_id, org_id, source)
GET    /tasks/{id}                  → detail + comments
PATCH  /tasks/{id}                  → update
POST   /tasks/{id}/transition       → change status
POST   /tasks/{id}/comments         → add comment
GET    /tasks/{id}/comments         → list comments

GET    /notifications               → current user's notifications
POST   /notifications/read-all      → mark all read
POST   /notifications/{id}/read     → mark one read

GET    /activity-feed               → merged recent activity
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models.audit_log import AuditLog
from app.models.process import Process, ProcessEvent, ProcessStep
from app.models.task import Notification, Task, TaskComment
from app.schemas.task import (
    ActivityFeedEntry,
    CommentRequest,
    CreateTaskRequest,
    NotificationResponse,
    TaskCommentResponse,
    TaskResponse,
    TransitionTaskRequest,
    UpdateTaskRequest,
)
from app.workflow.task_service import (
    InvalidTransition,
    TaskService,
)


tasks_router = APIRouter(tags=["tasks"])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])
activity_router = APIRouter(prefix="/activity-feed", tags=["activity"])


# -------------------- Tasks --------------------


@tasks_router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    body: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> TaskResponse:
    svc = TaskService(db)
    task = await svc.create(
        title=body.title,
        description=body.description,
        user_id=current_user.get("sub"),
        assignee_id=body.assignee_id and str(body.assignee_id),
        priority=body.priority,
        due_at=body.due_at,
        meta=body.metadata,
    )
    return TaskResponse(**_task_to_dict(task))


@tasks_router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    status: str | None = None,
    assignee_id: UUID | None = None,
    source: str | None = None,
    scope: str = Query("mine", pattern="^(mine|all)$"),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[TaskResponse]:
    svc = TaskService(db)
    if scope == "mine":
        tasks = await svc.list_for_user(
            current_user["sub"],
            statuses=[status] if status else None,
            limit=limit,
        )
    else:
        tasks = await svc.list(
            assignee_id=assignee_id and str(assignee_id),
            status=status,
            source=source,
            limit=limit,
        )
    return [TaskResponse(**_task_to_dict(t)) for t in tasks]


@tasks_router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> TaskResponse:
    task = await db.get(Task, str(task_id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(**_task_to_dict(task))


@tasks_router.get("/tasks/{task_id}/comments", response_model=list[TaskCommentResponse])
async def list_comments(
    task_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[TaskCommentResponse]:
    svc = TaskService(db)
    comments = await svc.list_comments(task_id)
    return [
        TaskCommentResponse(
            id=c.id, task_id=c.task_id, author_id=c.author_id,
            author_type=c.author_type, body=c.body, created_at=c.created_at,
        )
        for c in comments
    ]


@tasks_router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    body: UpdateTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> TaskResponse:
    svc = TaskService(db)
    try:
        task = await svc.update(
            task_id,
            title=body.title,
            description=body.description,
            assignee_id=body.assignee_id and str(body.assignee_id),
            priority=body.priority,
            due_at=body.due_at,
            actor_id=current_user.get("sub"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return TaskResponse(**_task_to_dict(task))


@tasks_router.post("/tasks/{task_id}/transition", response_model=TaskResponse)
async def transition_task(
    task_id: UUID,
    body: TransitionTaskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> TaskResponse:
    svc = TaskService(db)
    try:
        task = await svc.transition_status(
            task_id, body.to, actor_id=current_user.get("sub"),
        )
    except InvalidTransition as e:
        # Specific: 409 Conflict for state machine violations
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        # General: 400 Bad Request for invalid input
        raise HTTPException(status_code=400, detail=str(e))
    return TaskResponse(**_task_to_dict(task))


@tasks_router.post("/tasks/{task_id}/comments", response_model=TaskCommentResponse, status_code=201)
async def add_comment(
    task_id: UUID,
    body: CommentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> TaskCommentResponse:
    svc = TaskService(db)
    comment = await svc.add_comment(
        task_id, body.body,
        author_id=current_user.get("sub"),
        author_type="user",
    )
    return TaskCommentResponse(
        id=comment.id, task_id=comment.task_id,
        author_id=comment.author_id, author_type=comment.author_type,
        body=comment.body, created_at=comment.created_at,
    )


# -------------------- Notifications --------------------


@notifications_router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[NotificationResponse]:
    user_id = current_user["sub"]
    query = (
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    result = await db.execute(query)
    return [
        NotificationResponse(
            id=n.id, kind=n.kind, title=n.title, body=n.body,
            link=n.link, read_at=n.read_at, created_at=n.created_at,
        )
        for n in result.scalars()
    ]


@notifications_router.post("/read-all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    user_id = current_user["sub"]
    now = datetime.utcnow()
    result = await db.execute(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
        )
    )
    count = 0
    for n in result.scalars():
        n.read_at = now
        count += 1
    await db.commit()
    return {"marked_read": count}


@notifications_router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    n = await db.get(Notification, str(notification_id))
    if not n or n.user_id != current_user["sub"]:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.read_at = datetime.utcnow()
    await db.commit()
    return {"id": str(n.id), "read_at": n.read_at.isoformat()}


# -------------------- Activity feed --------------------


@activity_router.get("")
async def activity_feed(
    org_id: UUID | None = None,
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[ActivityFeedEntry]:
    """Merged feed: task.* + process.* + audit_log events.

    Sorted by created_at desc. Filters by org if provided.
    """
    entries: list[ActivityFeedEntry] = []

    # 1. Task events (task.created, task.<status>)
    task_q = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if org_id:
        task_q = task_q.where(Task.org_id == str(org_id))
    for t in (await db.execute(task_q)).scalars():
        entries.append(ActivityFeedEntry(
            id=f"task:{t.id}",
            source="task",
            action=f"task.{t.status}",
            title=t.title,
            body=t.description[:200] if t.description else None,
            actor_id=t.user_id,
            actor_type="user",
            created_at=t.created_at,
            link=f"/tasks/{t.id}",
        ))

    # 2. Process events
    proc_q = select(ProcessEvent).order_by(ProcessEvent.id.desc()).limit(limit)
    if org_id:
        proc_q = proc_q.join(Process, ProcessEvent.process_id == Process.id).where(
            Process.org_id == str(org_id)
        )
    for e in (await db.execute(proc_q)).scalars():
        entries.append(ActivityFeedEntry(
            id=f"proc:{e.id}",
            source="process",
            action=e.event_type,
            title=e.event_type,
            body=str(e.payload)[:200] if e.payload else None,
            actor_id=e.actor_id,
            actor_type="system",
            created_at=e.created_at,
            link=f"/processes/{e.process_id}",
        ))

    # 3. Audit log
    audit_q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if org_id:
        audit_q = audit_q.where(AuditLog.org_id == str(org_id))
    for a in (await db.execute(audit_q)).scalars():
        entries.append(ActivityFeedEntry(
            id=f"audit:{a.id}",
            source="audit",
            action=a.action,
            title=a.action,
            body=None,
            actor_id=a.actor_id,
            actor_type=a.actor_type,
            created_at=a.created_at,
            link=None,
        ))

    # Sort by created_at desc, take top limit
    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries[:limit]


# -------------------- Helpers --------------------


def _task_to_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "org_id": task.org_id,
        "user_id": task.user_id,
        "assignee_id": task.assignee_id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "source": task.source,
        "source_id": task.source_id,
        "due_at": task.due_at,
        "completed_at": task.completed_at,
        "created_at": task.created_at,
        "metadata": task.meta or {},
    }