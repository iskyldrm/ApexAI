"""Gates for the agent loop.

Two kinds:
- **Permission gates** (Task 15): check the user has the required
  permissions for a tool before invoking it.
- **Approval gates** (Task 30 + 31): detect sensitive actions
  (schema migrations, plan handoff) that need human sign-off.

A run that hits an approval gate is paused with
``status='awaiting_approval'`` and the user calls
``POST /agent/runs/{id}/resume`` to continue (Task 37).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.agent.roles import Role
    from app.agent.tools.base import Tool


# ---------------------------------------------------------------------------
# Permission gate (Task 15)
# ---------------------------------------------------------------------------


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

    if tool.role_visibility and role is not None and role not in tool.role_visibility:
        raise ToolPermissionError(
            f"Role {role.value} cannot invoke tool {tool.name!r}"
        )

    missing = set(tool.required_permissions) - user_permissions
    if missing:
        raise ToolPermissionError(
            f"Tool {tool.name!r} requires permissions not held: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# Approval gates (Tasks 30 + 31)
# ---------------------------------------------------------------------------


# Patterns that indicate a schema-migration command
_MIGRATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\balembic\s+upgrade\b", re.IGNORECASE),
    re.compile(r"\bprisma\s+migrate\s+deploy\b", re.IGNORECASE),
    re.compile(r"\bprisma\s+migrate\s+dev\b", re.IGNORECASE),
    re.compile(r"\bpython\s+manage\.py\s+migrate\b", re.IGNORECASE),
    re.compile(r"\bnode-prisma\s+migrate\b", re.IGNORECASE),
    re.compile(r"\bsqlx\s+migrate\s+run\b", re.IGNORECASE),
)


@dataclass
class GateDecision:
    """Result of evaluating a tool call against an approval gate."""

    trip: bool
    gate: Optional[str] = None  # "migration" | "plan_approval"
    reason: str = ""
    guidance: str = ""


def detect_migration_command(command: str) -> bool:
    """True if the command looks like a schema migration."""
    return any(p.search(command) for p in _MIGRATION_PATTERNS)


def evaluate_migration_gate(command: str) -> GateDecision:
    """Task 30: return GateDecision(trip=True) for migration commands."""
    if detect_migration_command(command):
        return GateDecision(
            trip=True,
            gate="migration",
            reason="Schema migration detected",
            guidance=(
                "⚠️ This command is a schema migration (alembic / prisma / django). "
                "Migrations cannot be rolled back automatically. The run is now "
                "awaiting your approval. Call POST /agent/runs/{id}/resume with "
                "{\"approval_comment\": \"approved\"} to proceed, or cancel the run."
            ),
        )
    return GateDecision(trip=False)


def evaluate_plan_approval_gate(role: str, last_tool_name: str | None) -> GateDecision:
    """Task 31: when ANL finishes, require approval before DEV picks up."""
    if role == "ANL" and last_tool_name in ("plan_finished", "request_plan_approval"):
        return GateDecision(
            trip=True,
            gate="plan_approval",
            reason="ANL plan complete; awaiting user approval",
            guidance=(
                "⚠️ The analyst has produced a plan. Review it via "
                "GET /agent/runs/{id}/export, then POST /agent/runs/{id}/resume "
                "to spawn a developer agent, or cancel if the plan needs rework."
            ),
        )
    return GateDecision(trip=False)
