"""Tool permission gate tests."""
import pytest

from app.agent.gates import ToolPermissionError, check_tool_permission
from app.agent.tools.base import Tool
from app.agent.tools.base import ToolContext, ToolResult


async def _noop(ctx, args):
    return ToolResult(ok=True)


def _tool(name: str, perms=(), role_visibility=()):
    return Tool(
        name=name,
        description="x",
        parameters_schema={"type": "object"},
        handler=_noop,
        required_permissions=perms,
        role_visibility=role_visibility,
    )


def test_pass_when_no_permissions_required():
    tool = _tool("read_file")
    check_tool_permission(tool, user_permissions=set())  # no raise


def test_pass_when_user_has_required_permission():
    tool = _tool("write_file", perms=("files:write",))
    check_tool_permission(tool, user_permissions={"files:write"})


def test_raise_when_missing_permission():
    tool = _tool("write_file", perms=("files:write",))
    with pytest.raises(ToolPermissionError) as exc_info:
        check_tool_permission(tool, user_permissions=set())
    assert "files:write" in str(exc_info.value)


def test_multiple_permissions_all_required():
    tool = _tool("deploy", perms=("files:write", "commands:run", "secrets:read"))
    check_tool_permission(tool, user_permissions={"files:write", "commands:run", "secrets:read"})
    with pytest.raises(ToolPermissionError):
        check_tool_permission(tool, user_permissions={"files:write"})


def test_role_visibility_enforced():
    from app.agent.roles import Role

    tool = _tool("admin_only", role_visibility=(Role.MANAGER,))
    check_tool_permission(tool, user_permissions=set(), role=Role.MANAGER)
    with pytest.raises(ToolPermissionError):
        check_tool_permission(tool, user_permissions=set(), role=Role.DEVELOPER_BE)


def test_empty_role_visibility_means_all_roles():
    from app.agent.roles import Role

    tool = _tool("everyone", role_visibility=())
    for role in Role:
        check_tool_permission(tool, user_permissions=set(), role=role)


def test_platform_admin_bypasses_permission_check():
    tool = _tool("write_file", perms=("files:write",))
    # Even with no permissions, platform admin is allowed
    check_tool_permission(tool, user_permissions=set(), is_platform_admin=True)
