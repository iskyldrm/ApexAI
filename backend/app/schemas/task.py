"""Pydantic schemas for the task tracking API."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


VALID_STATUSES = {"todo", "in_progress", "review", "done", "cancelled"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    assignee_id: UUID | None = None
    priority: str = Field(default="medium")
    due_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateTaskRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    assignee_id: UUID | None = None
    priority: str | None = None
    due_at: datetime | None = None


class TransitionTaskRequest(BaseModel):
    to: str = Field(description="Target status")


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=32_000)


class TaskResponse(BaseModel):
    id: UUID
    org_id: str | None
    user_id: str | None
    assignee_id: str | None
    title: str
    description: str | None
    status: str
    priority: str
    source: str
    source_id: UUID | None
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    metadata: dict[str, Any]


class TaskCommentResponse(BaseModel):
    id: UUID
    task_id: UUID
    author_id: str | None
    author_type: str
    body: str
    created_at: datetime


class NotificationResponse(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class ActivityFeedEntry(BaseModel):
    id: str
    source: str  # "task" | "agent_run" | "process" | "audit"
    action: str
    title: str
    body: str | None
    actor_id: str | None
    actor_type: str | None
    created_at: datetime
    link: str | None