"""Tool base interface + registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.agent.roles import Role


@dataclass
class ToolContext:
    """Per-invocation context passed to a tool."""

    agent_run_id: UUID
    user_id: str
    org_id: str | None
    work_dir: str
    allowed_paths: tuple[str, ...] = ()
    db_session: Any | None = None  # AsyncSession for tools that touch the DB
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Output of a tool call."""

    ok: bool = True
    output: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    """Declarative description of a tool the LLM can call."""

    name: str
    description: str
    parameters_schema: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]
    is_mutating: bool = False
    required_permissions: tuple[str, ...] = ()
    role_visibility: tuple["Role", ...] = ()  # empty = all roles

    def to_openai_schema(self) -> dict[str, Any]:
        """Render as OpenAI function-call schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
