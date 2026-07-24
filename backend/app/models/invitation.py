from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlmodel import Field

from app.models.base import BaseModel


class Invitation(BaseModel, table=True):
    __tablename__ = "invitations"

    org_id: str = Field(
        sa_column=Column(ForeignKey("orgs.id"), index=True, nullable=False)
    )
    email: str = Field(sa_column=Column(String(255), nullable=False))
    role: str = Field(sa_column=Column(String(32), nullable=False))
    team_ids: str = Field(sa_column=Column(String, nullable=False), default="[]")  # JSON
    token_hash: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    status: str = Field(
        sa_column=Column(String(32), nullable=False), default="pending"
    )
    invited_by: str = Field(sa_column=Column(String(36), nullable=False))