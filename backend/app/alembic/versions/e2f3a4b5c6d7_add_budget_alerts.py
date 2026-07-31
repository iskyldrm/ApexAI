"""add budget_alerts for Sub-System D cost optimization

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-07-31 14:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("actual", sa.Float(), nullable=False),
        sa.Column("period", sa.String(length=32), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_budget_alerts_created_at"),
        "budget_alerts",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_budget_alerts_org_id"),
        "budget_alerts",
        ["org_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_budget_alerts_kind"),
        "budget_alerts",
        ["kind"],
        unique=False,
    )
    op.create_index(
        "ix_budget_alerts_org_period_kind",
        "budget_alerts",
        ["org_id", "period", "kind"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_budget_alerts_org_period_kind", table_name="budget_alerts")
    op.drop_index(op.f("ix_budget_alerts_kind"), table_name="budget_alerts")
    op.drop_index(op.f("ix_budget_alerts_org_id"), table_name="budget_alerts")
    op.drop_index(op.f("ix_budget_alerts_created_at"), table_name="budget_alerts")
    op.drop_table("budget_alerts")