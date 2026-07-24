from datetime import datetime

from sqlalchemy import Column, String
from sqlmodel import Field

from app.models.base import BaseModel


class PlatformAdmin(BaseModel, table=True):
    __tablename__ = "platform_admins"

    email: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    password_hash: str = Field(sa_column=Column(String(255), nullable=False))
    full_name: str = Field(sa_column=Column(String(255), nullable=False))
    last_login_at: datetime | None = Field(default=None)