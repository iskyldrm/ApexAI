from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import ApiKeyProvider, IntegrationType


class ApiKeyCreate(BaseModel):
    provider: ApiKeyProvider
    label: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=10)
    org_id: UUID | None = None


class ApiKeyResponse(BaseModel):
    id: UUID
    provider: str
    label: str
    is_active: bool
    last_used_at: datetime | None
    org_id: UUID | None
    created_at: datetime


class IntegrationCreate(BaseModel):
    integration_type: IntegrationType
    label: str = Field(min_length=1, max_length=255)
    value: dict  # OAuth token, PAT, etc.
    org_id: UUID | None = None


class IntegrationResponse(BaseModel):
    id: UUID
    integration_type: str
    label: str
    is_active: bool
    org_id: UUID | None
    last_used_at: datetime | None
    created_at: datetime