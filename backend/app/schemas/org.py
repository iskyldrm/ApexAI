from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class OrgCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=255)
    admin_email: EmailStr
    admin_full_name: str = Field(min_length=1, max_length=255)


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    status: str | None = None


class OrgResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    created_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    description: str | None = None


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class TeamResponse(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    slug: str
    description: str | None
    created_at: datetime


class MembershipResponse(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID
    role: str
    status: str
    joined_at: datetime | None
    created_at: datetime