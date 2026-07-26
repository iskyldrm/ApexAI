"""Agent request/response schemas for the REST API."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ConverseRequest(BaseModel):
    """POST /agent/converse — start (or resume) an agent run."""

    role: str = Field(description="MGR | ANL | DEV_FE | DEV_BE | QA | PM | SUP")
    prompt: str = Field(min_length=1, max_length=32_000)
    work_dir: str = Field(description="Absolute path to the project directory")
    org_id: UUID | None = None
    max_steps: int | None = Field(default=None, ge=1, le=200)
    model_override: str | None = None
    # For resume flow
    resume_conversation_id: UUID | None = None
    resume_agent_run_id: UUID | None = None


class ConverseResponse(BaseModel):
    """Final result of an agent run."""

    success: bool
    agent_run_id: UUID
    conversation_id: UUID
    summary: str
    steps: int
    input_tokens: int
    output_tokens: int
    duration_ms: int
    intentional_files: list[str] = Field(default_factory=list)
    error: str | None = None
    finish_reason: str  # finished | max_steps | safety_tripped | budget_exceeded | error


class StreamEvent(BaseModel):
    """One SSE event in the streaming endpoint."""

    event: str  # agent.started | ai.thinking | tool.call | tool.result | agent.finished
    step: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
