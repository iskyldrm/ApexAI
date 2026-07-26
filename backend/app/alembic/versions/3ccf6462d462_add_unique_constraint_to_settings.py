"""add unique constraint to settings

Revision ID: 3ccf6462d462
Revises: b77518bfd34b
Create Date: 2026-07-26 19:28:14.915436

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
import sqlmodel


revision: str = '3ccf6462d462'
down_revision: Union[str, None] = 'b77518bfd34b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Deduplicate first in case a prior run created duplicates
    op.execute("""
        DELETE FROM settings
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY scope, COALESCE(scope_id, ''), key
                           ORDER BY created_at DESC
                       ) AS rn
                FROM settings
            ) t WHERE rn > 1
        )
    """)
    op.create_unique_constraint(
        "uq_settings_scope_scope_id_key",
        "settings",
        ["scope", "scope_id", "key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_settings_scope_scope_id_key", "settings", type_="unique")
