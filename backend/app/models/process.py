"""Process + ProcessStep + ProcessEvent + ProcessDLQ models (Sub-System B).

A Process is a multi-step workflow defined as a DAG. Each step is one
agent invocation. Events are append-only (event sourcing). DLQ holds
steps that exceeded max attempts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlmodel import Field

from app.models.base import BaseModel


class Process(BaseModel, table=True):
    """A multi-step workflow (DAG of agent invocations)."""

    __tablename__ = "processes"

    org_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, index=True),
    )
    user_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, index=True),
    )
    name: str = Field(sa_column=Column(String(255), nullable=False))
    definition: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
        description="DAG: {steps: [...], edges: [...]}",
    )
    status: str = Field(
        default="draft",
        sa_column=Column(String(32), nullable=False, index=True),
        description="draft | queued | running | paused | completed | failed | cancelled | stuck",
    )
    current_step: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    outputs: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    error: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )

    __table_args__ = (
        Index("ix_processes_org_status", "org_id", "status"),
    )


class ProcessStep(BaseModel, table=True):
    """One step (one node) in a Process DAG."""

    __tablename__ = "process_steps"

    process_id: UUID = Field(
        sa_column=Column(
            PgUUID(as_uuid=True),
            ForeignKey("processes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    step_name: str = Field(
        sa_column=Column(String(64), nullable=False),
        description="Unique within a process",
    )
    role: str = Field(sa_column=Column(String(16), nullable=False))
    status: str = Field(
        default="pending",
        sa_column=Column(String(32), nullable=False, index=True),
        description="pending | queued | running | completed | failed | skipped | cancelled | retrying",
    )
    attempt: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    max_attempts: int = Field(
        default=5,
        sa_column=Column(Integer, nullable=False, server_default="5"),
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
        description="Resolved inputs (template-expanded)",
    )
    outputs: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    prompt_template: str = Field(
        default="",
        sa_column=Column(Text, nullable=False, server_default=""),
    )
    agent_run_id: UUID | None = Field(
        default=None,
        sa_column=Column(PgUUID(as_uuid=True), nullable=True),
    )
    next_retry_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    error: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )

    __table_args__ = (
        Index("ix_process_steps_status_retry", "status", "next_retry_at"),
    )


class ProcessEvent(BaseModel, table=True):
    """Append-only event log (event sourcing)."""

    __tablename__ = "process_events"

    process_id: UUID = Field(
        sa_column=Column(
            PgUUID(as_uuid=True),
            ForeignKey("processes.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    step_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PgUUID(as_uuid=True),
            ForeignKey("process_steps.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    event_type: str = Field(
        sa_column=Column(String(64), nullable=False, index=True),
        description="process.created | process.started | step.queued | step.started | step.completed | step.failed | process.completed | ...",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    actor_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )

    __table_args__ = (
        Index("ix_process_events_process_id", "process_id", "id"),
    )


class ProcessDLQ(BaseModel, table=True):
    """Dead-letter queue for steps that exceeded max_attempts."""

    __tablename__ = "process_dlq"

    process_id: UUID | None = Field(
        default=None,
        sa_column=Column(PgUUID(as_uuid=True), nullable=True, index=True),
    )
    step_id: UUID | None = Field(
        default=None,
        sa_column=Column(PgUUID(as_uuid=True), nullable=True, index=True),
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    reason: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    retry_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    resolved_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    resolution: str | None = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
        description="replayed | abandoned | fixed",
    )

    __table_args__ = (
        Index(
            "ix_process_dlq_open",
            "resolved_at",
            postgresql_where=Column("resolved_at").is_(None),
        ),
    )
