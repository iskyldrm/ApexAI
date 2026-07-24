from datetime import datetime

from sqlalchemy import Column, String
from sqlmodel import Field

from app.models.base import BaseModel


class User(BaseModel, table=True):
    __tablename__ = "users"

    email: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    password_hash: str = Field(sa_column=Column(String(255), nullable=False))
    full_name: str = Field(sa_column=Column(String(255), nullable=False))
    is_active: bool = Field(default=True)
    email_verified_at: datetime | None = Field(default=None)
    last_login_at: datetime | None = Field(default=None)