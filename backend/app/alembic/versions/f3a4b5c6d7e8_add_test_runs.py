"""add test_runs + test_run_records for Sub-System E build/test pipeline

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-07-31 16:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "test_runs",
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
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("project_path", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("language", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("framework", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("network", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("image", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("output_path", sa.String(length=512), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_runs_created_at"), "test_runs", ["created_at"], unique=False)
    op.create_index(op.f("ix_test_runs_agent_run_id"), "test_runs", ["agent_run_id"], unique=False)
    op.create_index(op.f("ix_test_runs_language"), "test_runs", ["language"], unique=False)
    op.create_index(op.f("ix_test_runs_status"), "test_runs", ["status"], unique=False)
    op.create_index("ix_test_runs_project_started", "test_runs", ["project_path", "started_at"], unique=False)
    op.create_index("ix_test_runs_status_started", "test_runs", ["status", "started_at"], unique=False)

    op.create_table(
        "test_run_records",
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
        sa.Column("test_run_id", sa.Uuid(), nullable=False),
        sa.Column("test_name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_run_records_created_at"), "test_run_records", ["created_at"], unique=False)
    op.create_index(op.f("ix_test_run_records_test_run_id"), "test_run_records", ["test_run_id"], unique=False)
    op.create_index(op.f("ix_test_run_records_test_name"), "test_run_records", ["test_name"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_test_run_records_test_name"), table_name="test_run_records")
    op.drop_index(op.f("ix_test_run_records_test_run_id"), table_name="test_run_records")
    op.drop_index(op.f("ix_test_run_records_created_at"), table_name="test_run_records")
    op.drop_table("test_run_records")

    op.drop_index("ix_test_runs_status_started", table_name="test_runs")
    op.drop_index("ix_test_runs_project_started", table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_status"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_language"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_agent_run_id"), table_name="test_runs")
    op.drop_index(op.f("ix_test_runs_created_at"), table_name="test_runs")
    op.drop_table("test_runs")