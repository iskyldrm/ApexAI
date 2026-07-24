from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.enums import Role


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role
    team_ids: list[str] = Field(default_factory=list)


class InvitationAcceptRequest(BaseModel):
    token: str
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=1, max_length=255)


class InvitationResponse(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime