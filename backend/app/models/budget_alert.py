"""BudgetAlert model — fires once per org per day when daily spend crosses a threshold."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Column, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.base import BaseModel


class BudgetAlert(BaseModel, table=True):
    """A daily budget alert (50%, 90%, or 100% of daily cap)."""

    __tablename__ = "budget_alerts"

    org_id: str = Field(index=True)
    kind: str = Field(index=True)         # daily_50 | daily_90 | daily_100 | per_run_exceeded
    threshold: float                     # 0.50, 0.90, 1.00
    actual: float                        # actual pct at time of alert
    period: str                          # "2026-07-31"
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, server_default="{}"),
    )

    __table_args__ = (
        Index("ix_budget_alerts_org_period_kind", "org_id", "period", "kind"),
    )