"""AgentRun model — one row per agent invocation."""
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlmodel import Field

from app.models.base import BaseModel


class AgentRun(BaseModel, table=True):
    """A single agent invocation (one loop execution)."""

    __tablename__ = "agent_runs"

    conversation_id: UUID = Field(
        sa_column=Column(
            PgUUID(as_uuid=True),
            ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    user_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, index=True),
    )
    org_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, index=True),
    )
    role: str = Field(
        sa_column=Column(String(16), nullable=False, index=True),
    )
    provider: str | None = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    model: str | None = Field(
        default=None,
        sa_column=Column(String(128), nullable=True),
    )
    prompt_version: str | None = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    status: str = Field(
        default="running",
        sa_column=Column(String(32), nullable=False, index=True),
    )
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cost_usd: float = Field(default=0.0)
    duration_ms: int | None = Field(default=None)
    steps: int = Field(default=0)
    error: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(DateTime, nullable=False),
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
        Index("ix_agent_runs_user_started", "user_id", "started_at"),
        Index("ix_agent_runs_org_started", "org_id", "started_at"),
    )
