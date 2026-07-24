"""enable row-level security on tenant tables

Revision ID: ce739057c3f8
Revises: 6c1333a26530
Create Date: 2026-07-25 01:26:29.153160

This migration enables RLS on the tenant-scoped tables and creates policies
that read per-request context from PostgreSQL GUCs:

- ``app.current_user_id`` — UUID of the authenticated user (text form).
- ``app.is_platform_admin`` — 'true' if request runs as platform admin.

The app layer is responsible for calling:

    SELECT set_config('app.current_user_id', :uid, true),
           set_config('app.is_platform_admin', :is_admin, true)

at the start of every request (per transaction). Until that is in place,
queries against RLS-enabled tables return zero rows for non-platform-admins.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "ce739057c3f8"
down_revision: Union[str, None] = "6c1333a26530"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tenant_tables = [
        "orgs",
        "teams",
        "org_memberships",
        "team_memberships",
        "api_keys",
        "integration_credentials",
        "audit_log",
        "settings",
        "token_usage",
    ]
    for table in tenant_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")

    # org_memberships: user sees own + org admin sees all members of orgs
    # they administer.
    op.execute(
        """
        CREATE POLICY org_memberships_user_sees_own ON org_memberships
        FOR SELECT USING (user_id::text = current_setting('app.current_user_id', true));
        """
    )
    op.execute(
        """
        CREATE POLICY org_memberships_org_admin_sees_all ON org_memberships
        FOR SELECT USING (
            EXISTS (
                SELECT 1 FROM org_memberships om
                WHERE om.org_id = org_memberships.org_id
                  AND om.user_id::text = current_setting('app.current_user_id', true)
                  AND om.role = 'admin' AND om.status = 'active'
            ) OR current_setting('app.is_platform_admin', true) = 'true'
        );
        """
    )
    op.execute(
        """
        CREATE POLICY org_memberships_platform_admin ON org_memberships
        FOR ALL USING (current_setting('app.is_platform_admin', true) = 'true');
        """
    )

    # teams: any active member of the org can see the org's teams.
    op.execute(
        """
        CREATE POLICY teams_org_member_sees ON teams
        FOR SELECT USING (
            EXISTS (
                SELECT 1 FROM org_memberships om
                WHERE om.org_id = teams.org_id
                  AND om.user_id::text = current_setting('app.current_user_id', true)
                  AND om.status = 'active'
            ) OR current_setting('app.is_platform_admin', true) = 'true'
        );
        """
    )

    # settings: scope filters. scope_id is varchar; org_id / team_id are uuid,
    # so cast the UUID columns to text for comparison.
    op.execute(
        """
        CREATE POLICY settings_scope ON settings
        FOR SELECT USING (
            (scope = 'platform' AND current_setting('app.is_platform_admin', true) = 'true')
            OR (scope = 'org' AND scope_id IN (
                SELECT om.org_id::text FROM org_memberships om
                WHERE om.user_id::text = current_setting('app.current_user_id', true)
                  AND om.status = 'active'
            ))
            OR (scope = 'user' AND scope_id = current_setting('app.current_user_id', true))
            OR (scope = 'team' AND scope_id IN (
                SELECT tm.team_id::text FROM team_memberships tm
                WHERE tm.user_id::text = current_setting('app.current_user_id', true)
            ))
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS settings_scope ON settings;")
    op.execute("DROP POLICY IF EXISTS teams_org_member_sees ON teams;")
    op.execute(
        "DROP POLICY IF EXISTS org_memberships_platform_admin ON org_memberships;"
    )
    op.execute(
        "DROP POLICY IF EXISTS org_memberships_org_admin_sees_all ON org_memberships;"
    )
    op.execute("DROP POLICY IF EXISTS org_memberships_user_sees_own ON org_memberships;")
    for table in [
        "token_usage",
        "settings",
        "audit_log",
        "integration_credentials",
        "api_keys",
        "team_memberships",
        "org_memberships",
        "teams",
        "orgs",
    ]:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")