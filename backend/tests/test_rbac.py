import pytest
from fastapi import HTTPException

from app.core.rbac import require_permission, require_org_role, require_team_role
from app.enums import Permission, Role, TeamRole


def test_require_permission_grants_when_user_has_perm():
    @require_permission(Permission.TASKS_CREATE)
    async def handler(user_role: Role = Role.DEVELOPER) -> str:
        return "ok"

    import asyncio

    assert asyncio.run(handler()) == "ok"


def test_require_permission_denies_when_user_lacks_perm():
    @require_permission(Permission.ORG_MANAGE)
    async def handler(user_role: Role = Role.DEVELOPER) -> str:
        return "ok"

    import asyncio

    with pytest.raises(HTTPException) as exc:
        asyncio.run(handler())
    assert exc.value.status_code == 403


def test_require_permission_platform_admin_bypasses_check():
    @require_permission(Permission.ORG_MANAGE)
    async def handler(user_role: Role = Role.DEVELOPER, is_platform_admin: bool = False) -> str:
        return "ok"

    import asyncio

    assert asyncio.run(handler(is_platform_admin=True)) == "ok"


def test_require_org_role_allows_listed_role():
    @require_org_role([Role.ADMIN, Role.MANAGER])
    async def handler(user_role: Role = Role.MANAGER) -> str:
        return "ok"

    import asyncio

    assert asyncio.run(handler()) == "ok"


def test_require_org_role_denies_unlisted_role():
    @require_org_role([Role.ADMIN])
    async def handler(user_role: Role = Role.DEVELOPER) -> str:
        return "ok"

    import asyncio

    with pytest.raises(HTTPException):
        asyncio.run(handler())


def test_require_team_role_allows_matching():
    @require_team_role([TeamRole.LEAD, TeamRole.MEMBER])
    async def handler(user_team_roles: list = None) -> str:
        return "ok"

    import asyncio

    assert asyncio.run(handler(user_team_roles=[TeamRole.MEMBER])) == "ok"