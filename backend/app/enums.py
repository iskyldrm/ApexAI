from enum import Enum


class Role(str, Enum):
    """Org-wide role. 6 types per spec §5.2."""

    ADMIN = "admin"
    MANAGER = "manager"
    DEVELOPER = "developer"
    ANALYST = "analyst"
    TECH_SUPPORT = "tech_support"
    HR = "hr"


class TeamRole(str, Enum):
    """Team-level extra role per spec §5.3."""

    LEAD = "lead"
    MEMBER = "member"
    OBSERVER = "observer"


class Permission(str, Enum):
    """Permission-based RBAC per spec §5.1."""

    # Org
    ORG_MANAGE = "org:manage"
    ORG_VIEW = "org:view"
    # Users
    USERS_INVITE = "users:invite"
    USERS_MANAGE = "users:manage"
    USERS_VIEW = "users:view"
    # Teams
    TEAMS_MANAGE = "teams:manage"
    TEAMS_VIEW = "teams:view"
    # Tasks
    TASKS_CREATE = "tasks:create"
    TASKS_VIEW_ALL = "tasks:view:all"
    TASKS_VIEW_TEAM = "tasks:view:team"
    TASKS_VIEW_OWN = "tasks:view:own"
    TASKS_APPROVE = "tasks:approve"
    # Keys
    KEYS_MANAGE_ORG = "keys:manage:org"
    KEYS_MANAGE_OWN = "keys:manage:own"
    KEYS_VIEW_ALL = "keys:view:all"
    KEYS_VIEW_OWN = "keys:view:own"
    # Integrations
    INTEGRATIONS_MANAGE_ORG = "integrations:manage:org"
    INTEGRATIONS_MANAGE_OWN = "integrations:manage:own"
    INTEGRATIONS_VIEW = "integrations:view"
    # Audit
    AUDIT_VIEW = "audit:view"
    # Settings
    SETTINGS_MANAGE_ORG = "settings:manage:org"
    SETTINGS_MANAGE_OWN = "settings:manage:own"


# Role → Permission mapping per spec §5.2
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: {
        Permission.ORG_MANAGE,
        Permission.ORG_VIEW,
        Permission.USERS_INVITE,
        Permission.USERS_MANAGE,
        Permission.USERS_VIEW,
        Permission.TEAMS_MANAGE,
        Permission.TEAMS_VIEW,
        Permission.TASKS_CREATE,
        Permission.TASKS_VIEW_ALL,
        Permission.TASKS_VIEW_TEAM,
        Permission.TASKS_VIEW_OWN,
        Permission.TASKS_APPROVE,
        Permission.KEYS_MANAGE_ORG,
        Permission.KEYS_MANAGE_OWN,
        Permission.KEYS_VIEW_ALL,
        Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_ORG,
        Permission.INTEGRATIONS_MANAGE_OWN,
        Permission.INTEGRATIONS_VIEW,
        Permission.AUDIT_VIEW,
        Permission.SETTINGS_MANAGE_ORG,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.MANAGER: {
        Permission.ORG_VIEW,
        Permission.USERS_VIEW,
        Permission.TEAMS_VIEW,
        Permission.TASKS_CREATE,
        Permission.TASKS_VIEW_ALL,
        Permission.TASKS_VIEW_TEAM,
        Permission.TASKS_VIEW_OWN,
        Permission.TASKS_APPROVE,
        Permission.KEYS_MANAGE_OWN,
        Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_OWN,
        Permission.INTEGRATIONS_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.DEVELOPER: {
        Permission.ORG_VIEW,
        Permission.TEAMS_VIEW,
        Permission.TASKS_CREATE,
        Permission.TASKS_VIEW_TEAM,
        Permission.TASKS_VIEW_OWN,
        Permission.KEYS_MANAGE_OWN,
        Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_OWN,
        Permission.INTEGRATIONS_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.ANALYST: {
        Permission.ORG_VIEW,
        Permission.TEAMS_VIEW,
        Permission.TASKS_CREATE,
        Permission.TASKS_VIEW_ALL,
        Permission.TASKS_VIEW_OWN,
        Permission.TASKS_APPROVE,
        Permission.KEYS_MANAGE_OWN,
        Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_OWN,
        Permission.INTEGRATIONS_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.TECH_SUPPORT: {
        Permission.ORG_VIEW,
        Permission.TEAMS_VIEW,
        Permission.TASKS_VIEW_TEAM,
        Permission.TASKS_VIEW_OWN,
        Permission.KEYS_MANAGE_OWN,
        Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_ORG,
        Permission.INTEGRATIONS_MANAGE_OWN,
        Permission.INTEGRATIONS_VIEW,
        Permission.AUDIT_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.HR: {
        Permission.ORG_VIEW,
        Permission.TEAMS_VIEW,
        Permission.USERS_INVITE,
        Permission.USERS_MANAGE,
        Permission.USERS_VIEW,
        Permission.TASKS_VIEW_TEAM,
        Permission.TASKS_VIEW_OWN,
        Permission.KEYS_MANAGE_OWN,
        Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_OWN,
        Permission.INTEGRATIONS_VIEW,
        Permission.AUDIT_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
}


def has_permission(role: Role, permission: Permission) -> bool:
    """Check if a role grants a specific permission."""
    return permission in ROLE_PERMISSIONS.get(role, set())


class OrgStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class MembershipStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SUSPENDED = "suspended"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ApiKeyProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class IntegrationType(str, Enum):
    GITHUB_APP = "github_app"
    GITHUB_OAUTH = "github_oauth"
    GITHUB_PAT = "github_pat"
    TELEGRAM_BOT = "telegram_bot"
    AZURE_SP = "azure_sp"


class AuditActorType(str, Enum):
    USER = "user"
    PLATFORM_ADMIN = "platform_admin"
    SYSTEM = "system"


class SettingScope(str, Enum):
    PLATFORM = "platform"
    ORG = "org"
    TEAM = "team"
    USER = "user"
