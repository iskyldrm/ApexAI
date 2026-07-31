"""TestRun model — one row per test execution."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Column, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlmodel import Field

from app.models.base import BaseModel


class TestRun(BaseModel, table=True):
    """A single test execution."""

    __tablename__ = "test_runs"

    agent_run_id: UUID | None = Field(
        default=None,
        sa_column=Column(PgUUID(as_uuid=True), nullable=True, index=True),
    )
    project_path: str = Field(default="")
    language: str = Field(default="", index=True)
    framework: str = Field(default="")
    status: str = Field(default="running", index=True)  # running|passed|failed|errored|timeout
    total: int = Field(default=0)
    passed: int = Field(default=0)
    failed: int = Field(default=0)
    skipped: int = Field(default=0)
    errors: int = Field(default=0)
    duration_ms: int | None = Field(default=None)
    network: bool = Field(default=False)
    image: str = Field(default="")
    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column("started_at", nullable=False),
    )
    finished_at: datetime | None = Field(default=None)
    output_path: str | None = Field(default=None)
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )

    __table_args__ = (
        Index("ix_test_runs_project_started", "project_path", "started_at"),
        Index("ix_test_runs_status_started", "status", "started_at"),
    )


class TestRunRecord(BaseModel, table=True):
    """Per-test record within a run — used for flakiness detection."""

    __tablename__ = "test_run_records"

    test_run_id: UUID = Field(
        sa_column=Column(
            PgUUID(as_uuid=True),
            ForeignKey("test_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    test_name: str = Field(index=True)         # e.g. "tests/test_foo.py::test_bar"
    status: str = Field()                       # passed | failed | skipped | errored
    duration_ms: int = Field(default=0)

    __table_args__ = (
        Index("ix_test_run_records_test_name", "test_name"),
    )