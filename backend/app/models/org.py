from sqlalchemy import Column, String
from sqlmodel import Field

from app.models.base import BaseModel


class Org(BaseModel, table=True):
    __tablename__ = "orgs"

    slug: str = Field(
        sa_column=Column(String(64), unique=True, index=True, nullable=False)
    )
    name: str = Field(sa_column=Column(String(255), nullable=False))
    status: str = Field(sa_column=Column(String(32), nullable=False), default="active")
    settings: str = Field(sa_column=Column(String, nullable=False), default="{}")
    created_by: str | None = Field(default=None)  # PlatformAdmin UUID as string