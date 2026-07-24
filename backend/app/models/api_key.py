from datetime import datetime

from sqlalchemy import CheckConstraint, Column, ForeignKey, String
from sqlmodel import Field

from app.models.base import BaseModel


class ApiKey(BaseModel, table=True):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "(org_id IS NULL) != (user_id IS NULL)",
            name="api_keys_owner_xor",
        ),
    )

    org_id: str | None = Field(
        default=None, sa_column=Column(ForeignKey("orgs.id"), index=True)
    )
    user_id: str | None = Field(
        default=None, sa_column=Column(ForeignKey("users.id"), index=True)
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    label: str = Field(sa_column=Column(String(255), nullable=False))
    vault_path: str = Field(sa_column=Column(String(512), nullable=False))
    is_active: bool = Field(default=True)
    last_used_at: datetime | None = Field(default=None)
    created_by: str = Field(sa_column=Column(String(36), nullable=False))