"""Pydantic schemas for the workflow REST API."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class StepDefIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=16)
    prompt: str = Field(min_length=1, max_length=32_000)
    max_attempts: int | None = Field(default=None, ge=1, le=20)


class EdgeDefIn(BaseModel):
    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)

    model_config = {"populate_by_name": True}


class CreateProcessRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    steps: list[StepDefIn] = Field(min_length=1, max_length=50)
    edges: list[EdgeDefIn] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    work_dir: str | None = None


class ProcessStepResponse(BaseModel):
    id: UUID
    step_name: str
    role: str
    status: str
    attempt: int
    max_attempts: int
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    next_retry_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    agent_run_id: UUID | None


class ProcessEventResponse(BaseModel):
    id: UUID
    event_type: str
    payload: dict[str, Any]
    actor_id: str | None
    step_id: UUID | None
    created_at: datetime


class ProcessResponse(BaseModel):
    id: UUID
    name: str
    status: str
    current_step: str | None
    definition: dict[str, Any]
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: list[ProcessStepResponse] = Field(default_factory=list)
