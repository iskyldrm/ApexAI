from decimal import Decimal

from sqlalchemy import Column, ForeignKey, Numeric, String
from sqlmodel import Field

from app.models.base import BaseModel


class TokenUsage(BaseModel, table=True):
    __tablename__ = "token_usage"

    user_id: str = Field(
        sa_column=Column(ForeignKey("users.id"), index=True, nullable=False)
    )
    org_id: str = Field(
        sa_column=Column(ForeignKey("orgs.id"), index=True, nullable=False)
    )
    api_key_id: str = Field(sa_column=Column(ForeignKey("api_keys.id"), nullable=False))
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    model: str = Field(sa_column=Column(String(64), nullable=False))
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cost_usd: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(10, 6), nullable=False),
    )