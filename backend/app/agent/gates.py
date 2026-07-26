"""Permission + role gates for tool invocation.

Runs before each tool execution. Raises ``ToolPermissionError`` if the
tool's ``required_permissions`` are not all held by the user, or if the
tool's ``role_visibility`` excludes the agent's role.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.roles import Role
    from app.agent.tools.base import Tool


class ToolPermissionError(PermissionError):
    """Raised when a tool is invoked without the required permissions."""


def check_tool_permission(
    tool: "Tool",
    user_permissions: set[str],
    role: "Role | None" = None,
    is_platform_admin: bool = False,
) -> None:
    """Raise ``ToolPermissionError`` if the user can't invoke this tool.

    Platform admins bypass both permission and role checks.
    """
    if is_platform_admin:
        return

    # Role visibility
    if tool.role_visibility and role is not None and role not in tool.role_visibility:
        raise ToolPermissionError(
            f"Role {role.value} cannot invoke tool {tool.name!r}"
        )

    # Required permissions
    missing = set(tool.required_permissions) - user_permissions
    if missing:
        raise ToolPermissionError(
            f"Tool {tool.name!r} requires permissions not held: {sorted(missing)}"
        )
