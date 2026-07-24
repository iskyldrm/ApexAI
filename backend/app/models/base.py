from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Timezone-aware UTC now (Python 3.12+ deprecates naive utcnow())."""
    return datetime.now(UTC)


class BaseModel(SQLModel):
    """Base for all persistent models. Mixin, not a standalone table.

    Subclass with `table=True` to declare a SQLModel table:
        class User(BaseModel, table=True):
            __tablename__ = "users"
            email: str
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=_utcnow, nullable=False, index=True)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)
