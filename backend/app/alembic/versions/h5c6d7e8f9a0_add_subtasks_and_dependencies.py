"""add tasks.parent_id + task_dependencies table for Sub-System C hardening

Revision ID: h5c6d7e8f9a0
Revises: g4b5c6d7e8f9
Create Date: 2026-07-31 20:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "h5c6d7e8f9a0"
down_revision: Union[str, None] = "g4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Sub-tasks
    op.add_column(
        "tasks",
        sa.Column("parent_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_parent_id",
        "tasks",
        "tasks",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_tasks_parent_id"), "tasks", ["parent_id"], unique=False)

    # Dependencies
    op.create_table(
        "task_dependencies",
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
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_id", sa.Uuid(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.ForeignKeyConstraint(["blocker_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Prevent self-dependency
        sa.CheckConstraint("blocker_id != blocked_id", name="task_dep_no_self"),
    )
    op.create_index(op.f("ix_task_dependencies_created_at"), "task_dependencies", ["created_at"], unique=False)
    op.create_index(op.f("ix_task_dependencies_blocker_id"), "task_dependencies", ["blocker_id"], unique=False)
    op.create_index(op.f("ix_task_dependencies_blocked_id"), "task_dependencies", ["blocked_id"], unique=False)
    op.create_index(
        "ix_task_dependencies_blocker_blocked",
        "task_dependencies",
        ["blocker_id", "blocked_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_task_dependencies_blocker_blocked", table_name="task_dependencies")
    op.drop_index(op.f("ix_task_dependencies_blocked_id"), table_name="task_dependencies")
    op.drop_index(op.f("ix_task_dependencies_blocker_id"), table_name="task_dependencies")
    op.drop_index(op.f("ix_task_dependencies_created_at"), table_name="task_dependencies")
    op.drop_table("task_dependencies")

    op.drop_index(op.f("ix_tasks_parent_id"), table_name="tasks")
    op.drop_constraint("fk_tasks_parent_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "parent_id")