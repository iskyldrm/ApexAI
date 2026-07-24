from sqlalchemy import Column, ForeignKey, String
from sqlmodel import JSON, Field

from app.models.base import BaseModel


class AuditLog(BaseModel, table=True):
    __tablename__ = "audit_log"

    actor_type: str = Field(sa_column=Column(String(32), nullable=False))
    actor_id: str | None = Field(default=None, index=True)
    actor_email_snapshot: str | None = Field(default=None)
    action: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    target_type: str | None = Field(default=None)
    target_id: str | None = Field(default=None)
    org_id: str | None = Field(
        default=None, sa_column=Column(ForeignKey("orgs.id"), index=True)
    )
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    meta: dict = Field(default={}, sa_column=Column(JSON, nullable=False))