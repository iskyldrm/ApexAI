from sqlalchemy import Column, ForeignKey, String
from sqlmodel import Field

from app.models.base import BaseModel


class Team(BaseModel, table=True):
    __tablename__ = "teams"

    org_id: str = Field(
        sa_column=Column(ForeignKey("orgs.id"), index=True, nullable=False)
    )
    name: str = Field(sa_column=Column(String(255), nullable=False))
    slug: str = Field(sa_column=Column(String(64), nullable=False))
    description: str | None = Field(default=None)
    created_by: str | None = Field(default=None)