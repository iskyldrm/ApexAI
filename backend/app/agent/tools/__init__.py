"""Tool registry — a singleton that owns all registered Tool instances."""
from app.agent.tools.base import Tool, ToolContext, ToolResult
from app.agent.roles import Role  # noqa: F401 (re-export for tool authors)


class ToolRegistry:
    """Module-level singleton holding all tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def get_for_role(self, role: Role) -> list[Tool]:
        out = []
        for tool in self._tools.values():
            if not tool.role_visibility or role in tool.role_visibility:
                out.append(tool)
        return out

    def reset(self) -> None:
        self._tools.clear()


registry = ToolRegistry()
