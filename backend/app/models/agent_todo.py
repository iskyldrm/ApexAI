"""AgentTodo — per-agent-run checklist of planned steps."""
from sqlalchemy import Column, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlmodel import Field

from app.models.base import BaseModel


class AgentTodo(BaseModel, table=True):
    """One planned step in an agent run."""

    __tablename__ = "agent_todos"

    agent_run_id: str = Field(
        sa_column=Column(PgUUID(as_uuid=True), nullable=False, index=True),
    )
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    title: str = Field(sa_column=Column(String(255), nullable=False))
    status: str = Field(
        default="pending",
        sa_column=Column(String(16), nullable=False),
        description="pending | in_progress | done | skipped | failed",
    )
    notes: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    __table_args__ = (
        Index("ix_agent_todos_run_seq", "agent_run_id", "sequence"),
    )
