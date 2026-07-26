"""Tool registry — a singleton that owns all registered Tool instances."""
from app.agent.roles import Role  # noqa: F401 (re-export for tool authors)
from app.agent.tools.apply_patch import ApplyPatchTool
from app.agent.tools.ask_user import AskUserTool
from app.agent.tools.ast_grep import AstGrepTool
from app.agent.tools.base import Tool, ToolContext, ToolResult
from app.agent.tools.edit_file import EditFileTool
from app.agent.tools.find_files import FindFilesTool
from app.agent.tools.git_diff import GitDiffTool
from app.agent.tools.git_status import GitStatusTool
from app.agent.tools.grep_search import GrepSearchTool
from app.agent.tools.http_request import HttpRequestTool
from app.agent.tools.list_dir import ListDirTool
from app.agent.tools.list_todos import ListTodosTool
from app.agent.tools.read_file import ReadFileTool
from app.agent.tools.run_command import RunCommandTool
from app.agent.tools.run_subagent import RunSubagentTool
from app.agent.tools.run_tests import RunTestsTool
from app.agent.tools.update_todo import UpdateTodoTool
from app.agent.tools.write_file import WriteFileTool


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

# Default registration — every tool the agent runtime knows about.
# HttpRequestTool and AskUserTool need per-tenant config (URL allowlist, answer
# provider) — callers should re-register these with the right settings.
_DEFAULT_TOOLS: list[Tool] = [
    ReadFileTool(),
    ListDirTool(),
    FindFilesTool(),
    GrepSearchTool(),
    AstGrepTool(),
    WriteFileTool(),
    EditFileTool(),
    ApplyPatchTool(),
    RunCommandTool(),
    RunTestsTool(),
    GitStatusTool(),
    GitDiffTool(),
    RunSubagentTool(),
    UpdateTodoTool(),
    ListTodosTool(),
    AskUserTool(),
    HttpRequestTool(),  # permissive: no allowed_hosts by default
]
for t in _DEFAULT_TOOLS:
    registry.register(t)

