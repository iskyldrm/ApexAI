from datetime import datetime

from sqlalchemy import Column, ForeignKey, String
from sqlmodel import Field

from app.models.base import BaseModel


class OrgMembership(BaseModel, table=True):
    __tablename__ = "org_memberships"

    org_id: str = Field(
        sa_column=Column(ForeignKey("orgs.id"), index=True, nullable=False)
    )
    user_id: str = Field(
        sa_column=Column(ForeignKey("users.id"), index=True, nullable=False)
    )
    role: str = Field(sa_column=Column(String(32), nullable=False))
    status: str = Field(sa_column=Column(String(32), nullable=False), default="active")
    invited_by: str | None = Field(default=None)
    joined_at: datetime | None = Field(default=None)


class TeamMembership(BaseModel, table=True):
    __tablename__ = "team_memberships"

    team_id: str = Field(
        sa_column=Column(ForeignKey("teams.id"), index=True, nullable=False)
    )
    user_id: str = Field(
        sa_column=Column(ForeignKey("users.id"), index=True, nullable=False)
    )
    team_role: str = Field(sa_column=Column(String(32), nullable=False))
    added_by: str | None = Field(default=None)