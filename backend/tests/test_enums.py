from app.enums import (
    ApiKeyProvider,
    IntegrationType,
    OrgStatus,
    Permission,
    Role,
)


def test_role_enum_values():
    assert Role.ADMIN == "admin"
    assert Role.MANAGER == "manager"
    assert Role.DEVELOPER == "developer"
    assert Role.ANALYST == "analyst"
    assert Role.TECH_SUPPORT == "tech_support"
    assert Role.HR == "hr"


def test_permission_enum_values():
    assert Permission.ORG_MANAGE == "org:manage"
    assert Permission.TASKS_CREATE == "tasks:create"


def test_api_key_provider_enum():
    assert ApiKeyProvider.OPENAI == "openai"
    assert ApiKeyProvider.ANTHROPIC == "anthropic"
    assert ApiKeyProvider.GOOGLE == "google"
    assert ApiKeyProvider.OLLAMA == "ollama"
    assert ApiKeyProvider.CUSTOM == "custom"


def test_integration_type_enum():
    assert IntegrationType.GITHUB_APP == "github_app"
    assert IntegrationType.GITHUB_OAUTH == "github_oauth"
    assert IntegrationType.GITHUB_PAT == "github_pat"
    assert IntegrationType.TELEGRAM_BOT == "telegram_bot"
    assert IntegrationType.AZURE_SP == "azure_sp"


def test_org_status_enum():
    assert OrgStatus.ACTIVE == "active"
    assert OrgStatus.SUSPENDED == "suspended"
    assert OrgStatus.DELETED == "deleted"
