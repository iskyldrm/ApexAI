"""Conversation + ConversationMessage models for agent runtime (Sub-System A)."""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlmodel import Field, SQLModel

from app.models.base import BaseModel


class Conversation(BaseModel, table=True):
    """A single agent run's conversation metadata."""

    __tablename__ = "conversations"

    role: str = Field(
        sa_column=Column(String(16), nullable=False, index=True),
        description="Role (MGR, ANL, DEV_FE, etc.)",
    )
    status: str = Field(
        default="running",
        sa_column=Column(String(32), nullable=False, index=True),
        description="running | finished | failed | paused | awaiting_approval",
    )
    user_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, index=True),
    )
    org_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, index=True),
    )
    parent_run_id: UUID | None = Field(
        default=None,
        sa_column=Column(PgUUID(as_uuid=True), nullable=True, index=True),
        description="FK loop for sub-agents",
    )
    summary: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    total_input_tokens: int = Field(default=0)
    total_output_tokens: int = Field(default=0)
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


class ConversationMessage(BaseModel, table=True):
    """A single message in a conversation (user, assistant, tool, system)."""

    __tablename__ = "conversation_messages"

    conversation_id: UUID = Field(
        sa_column=Column(
            PgUUID(as_uuid=True),
            ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    role: str = Field(
        sa_column=Column(String(16), nullable=False),
        description="user | assistant | tool | system",
    )
    content: str = Field(
        default="",
        sa_column=Column(Text, nullable=False, server_default=""),
    )
    tool_calls: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    tool_result: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    tool_name: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    tool_call_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    parent_message_id: UUID | None = Field(
        default=None,
        sa_column=Column(PgUUID(as_uuid=True), nullable=True, index=True),
        description="FK for branching (sub-agents)",
    )
    sequence: int = Field(
        default=0,
        sa_column=Column(nullable=False, server_default="0"),
    )

    __table_args__ = (
        Index(
            "ix_conversation_messages_conv_sequence",
            "conversation_id",
            "sequence",
        ),
    )
