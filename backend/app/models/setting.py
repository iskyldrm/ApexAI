from sqlalchemy import Column, String
from sqlmodel import JSON, Field

from app.models.base import BaseModel


class Setting(BaseModel, table=True):
    __tablename__ = "settings"

    scope: str = Field(sa_column=Column(String(32), nullable=False))
    scope_id: str | None = Field(default=None, index=True)
    key: str = Field(sa_column=Column(String(128), nullable=False))
    value: dict = Field(default={}, sa_column=Column(JSON, nullable=False))
    enforced_by_admin: bool = Field(default=False)
    updated_by: str | None = Field(default=None)