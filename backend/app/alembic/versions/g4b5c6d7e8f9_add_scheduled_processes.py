"""add scheduled_processes + workflow_templates for Sub-System B hardening

Revision ID: g4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-07-31 18:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "g4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_processes",
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
        sa.Column("process_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=True),
        sa.Column("cron_expr", sa.String(length=64), nullable=False, server_default="0 9 * * *"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=False), nullable=True),
        sa.ForeignKeyConstraint(["process_id"], ["processes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scheduled_processes_created_at"), "scheduled_processes", ["created_at"], unique=False)
    op.create_index(op.f("ix_scheduled_processes_process_id"), "scheduled_processes", ["process_id"], unique=False)
    op.create_index(op.f("ix_scheduled_processes_org_id"), "scheduled_processes", ["org_id"], unique=False)

    op.create_table(
        "workflow_templates",
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
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="custom"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workflow_templates_created_at"), "workflow_templates", ["created_at"], unique=False)
    op.create_index(op.f("ix_workflow_templates_name"), "workflow_templates", ["name"], unique=False)
    op.create_index(op.f("ix_workflow_templates_category"), "workflow_templates", ["category"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workflow_templates_category"), table_name="workflow_templates")
    op.drop_index(op.f("ix_workflow_templates_name"), table_name="workflow_templates")
    op.drop_index(op.f("ix_workflow_templates_created_at"), table_name="workflow_templates")
    op.drop_table("workflow_templates")

    op.drop_index(op.f("ix_scheduled_processes_org_id"), table_name="scheduled_processes")
    op.drop_index(op.f("ix_scheduled_processes_process_id"), table_name="scheduled_processes")
    op.drop_index(op.f("ix_scheduled_processes_created_at"), table_name="scheduled_processes")
    op.drop_table("scheduled_processes")