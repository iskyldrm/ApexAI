"""add composite indexes for hot queries

Revision ID: 6c1333a26530
Revises: 04f212152c55
Create Date: 2026-07-25 01:26:07.183209

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "6c1333a26530"
down_revision: Union[str, None] = "04f212152c55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # api_keys hot path: lookup by org or user + provider + active flag
    op.create_index(
        "idx_api_keys_org_provider",
        "api_keys",
        ["org_id", "provider", "is_active"],
    )
    op.create_index(
        "idx_api_keys_user_provider",
        "api_keys",
        ["user_id", "provider", "is_active"],
    )

    # audit_log hot path: most recent by org / actor
    op.create_index(
        "idx_audit_log_org_created",
        "audit_log",
        ["org_id", text("created_at DESC")],
    )
    op.create_index(
        "idx_audit_log_actor_created",
        "audit_log",
        ["actor_id", text("created_at DESC")],
    )

    # token_usage hot path: aggregated by org / user over time
    op.create_index(
        "idx_token_usage_org_created",
        "token_usage",
        ["org_id", text("created_at DESC")],
    )
    op.create_index(
        "idx_token_usage_user_created",
        "token_usage",
        ["user_id", text("created_at DESC")],
    )

    # settings: enforce one row per (scope, scope_id, key)
    op.create_index(
        "idx_settings_scope_key",
        "settings",
        ["scope", "scope_id", "key"],
        unique=True,
    )

    # teams: unique slug per org
    op.create_index(
        "idx_teams_org_slug",
        "teams",
        ["org_id", "slug"],
        unique=True,
    )

    # org memberships: one membership per (org, user)
    op.create_index(
        "idx_org_memberships_org_user",
        "org_memberships",
        ["org_id", "user_id"],
        unique=True,
    )

    # team memberships: one membership per (team, user)
    op.create_index(
        "idx_team_memberships_team_user",
        "team_memberships",
        ["team_id", "user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_team_memberships_team_user", "team_memberships")
    op.drop_index("idx_org_memberships_org_user", "org_memberships")
    op.drop_index("idx_teams_org_slug", "teams")
    op.drop_index("idx_settings_scope_key", "settings")
    op.drop_index("idx_token_usage_user_created", "token_usage")
    op.drop_index("idx_token_usage_org_created", "token_usage")
    op.drop_index("idx_audit_log_actor_created", "audit_log")
    op.drop_index("idx_audit_log_org_created", "audit_log")
    op.drop_index("idx_api_keys_user_provider", "api_keys")
    op.drop_index("idx_api_keys_org_provider", "api_keys")