"""AgentRunCheckpoint model — periodic snapshots for failure recovery.

A checkpoint captures the minimum state needed to resume an ``AgentLoop``
after a worker crash: the current step number, accumulated tokens,
intentional files, and a serialized view of the in-flight messages.

We do NOT serialize the full conversation (it already lives in
``conversation_messages``) — only the runtime bookkeeping.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Column, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlmodel import Field

from app.models.base import BaseModel


class AgentRunCheckpoint(BaseModel, table=True):
    """A periodic snapshot of agent loop state for crash recovery."""

    __tablename__ = "agent_run_checkpoints"

    agent_run_id: UUID = Field(
        sa_column=Column(
            PgUUID(as_uuid=True),
            ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    step: int = Field(default=0, index=True)
    # Bookkeeping state (input_tokens/output_tokens/intentional_files/etc.)
    state: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # The latest assistant message id, useful for resume
    last_message_id: UUID | None = Field(
        default=None,
        sa_column=Column(PgUUID(as_uuid=True), nullable=True),
    )

    __table_args__ = (
        Index(
            "ix_agent_run_checkpoints_run_step",
            "agent_run_id",
            "step",
        ),
    )