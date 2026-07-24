"""Basic tests for F platform models — verify all 15 tables register on SQLModel.metadata."""
from sqlmodel import SQLModel

from app.models import (
    ApiKey,
    AuditLog,
    EmailVerificationToken,
    IntegrationCredential,
    Invitation,
    Org,
    OrgMembership,
    PasswordResetToken,
    PlatformAdmin,
    RefreshToken,
    Setting,
    Team,
    TeamMembership,
    TokenUsage,
    User,
)


def _expected_tables() -> set[str]:
    return {
        "platform_admins",
        "users",
        "orgs",
        "teams",
        "org_memberships",
        "team_memberships",
        "invitations",
        "api_keys",
        "integration_credentials",
        "audit_log",
        "settings",
        "token_usage",
        "password_reset_tokens",
        "email_verification_tokens",
        "refresh_tokens",
    }


def test_all_15_tables_registered():
    expected = _expected_tables()
    registered = {t.name for t in SQLModel.metadata.tables.values()}
    missing = expected - registered
    assert not missing, f"Missing tables in metadata: {missing}"
    # Note: test_models_base.py pollutes metadata with TestModel tables —
    # those are not part of the F spec and are filtered here.


def test_platform_admin_tablename():
    assert PlatformAdmin.__tablename__ == "platform_admins"


def test_user_tablename():
    assert User.__tablename__ == "users"


def test_org_tablename():
    assert Org.__tablename__ == "orgs"


def test_team_tablename():
    assert Team.__tablename__ == "teams"


def test_membership_tablename():
    assert OrgMembership.__tablename__ == "org_memberships"
    assert TeamMembership.__tablename__ == "team_memberships"


def test_invitation_tablename():
    assert Invitation.__tablename__ == "invitations"


def test_api_key_tablename_and_xor_constraint():
    assert ApiKey.__tablename__ == "api_keys"
    # CheckConstraint registered on the table
    table = ApiKey.__table__
    constraints = {c.name for c in table.constraints if hasattr(c, "name")}
    assert "api_keys_owner_xor" in constraints


def test_integration_credential_tablename_and_xor_constraint():
    assert IntegrationCredential.__tablename__ == "integration_credentials"
    table = IntegrationCredential.__table__
    constraints = {c.name for c in table.constraints if hasattr(c, "name")}
    assert "integration_credentials_owner_xor" in constraints


def test_audit_log_tablename():
    assert AuditLog.__tablename__ == "audit_log"


def test_setting_tablename():
    assert Setting.__tablename__ == "settings"


def test_token_usage_tablename():
    assert TokenUsage.__tablename__ == "token_usage"


def test_auth_tokens_tablename():
    assert PasswordResetToken.__tablename__ == "password_reset_tokens"
    assert EmailVerificationToken.__tablename__ == "email_verification_tokens"
    assert RefreshToken.__tablename__ == "refresh_tokens"