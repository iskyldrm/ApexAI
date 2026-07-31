"""add agent_run_checkpoints for failure recovery (Sub-System A hardening A.9)

Revision ID: d1e2f3a4b5c6
Revises: 911b005fad39
Create Date: 2026-07-31 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "911b005fad39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_run_checkpoints",
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
        sa.Column(
            "agent_run_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column("step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "last_message_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_run_checkpoints_created_at"),
        "agent_run_checkpoints",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_checkpoints_agent_run_id"),
        "agent_run_checkpoints",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_run_checkpoints_step"),
        "agent_run_checkpoints",
        ["step"],
        unique=False,
    )
    op.create_index(
        "ix_agent_run_checkpoints_run_step",
        "agent_run_checkpoints",
        ["agent_run_id", "step"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_run_checkpoints_run_step", table_name="agent_run_checkpoints")
    op.drop_index(op.f("ix_agent_run_checkpoints_step"), table_name="agent_run_checkpoints")
    op.drop_index(op.f("ix_agent_run_checkpoints_agent_run_id"), table_name="agent_run_checkpoints")
    op.drop_index(op.f("ix_agent_run_checkpoints_created_at"), table_name="agent_run_checkpoints")
    op.drop_table("agent_run_checkpoints")