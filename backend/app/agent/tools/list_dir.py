"""list_dir tool — enumerate files and directories."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from app.agent.sandbox import SandboxError, safe_resolve_path
from app.agent.tools.base import Tool, ToolContext, ToolResult


class ListDirTool(Tool):
    """List directory contents. Supports glob and recursive modes."""

    def __init__(self) -> None:
        super().__init__(
            name="list_dir",
            description=(
                "List files and subdirectories in a path. Supports glob pattern "
                "and recursion. Hidden files (starting with .) are included by default."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to work_dir"},
                    "recursive": {"type": "boolean", "default": False},
                    "pattern": {"type": "string", "description": "Glob pattern, e.g. '*.py'"},
                },
                "required": ["path"],
            },
            handler=self._run,
            is_mutating=False,
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        try:
            abs_path = safe_resolve_path(ctx.work_dir, args["path"], ctx.allowed_paths)
        except SandboxError as e:
            return ToolResult(ok=False, error=str(e))

        root = Path(abs_path)
        if not root.exists():
            return ToolResult(ok=False, error=f"Path not found: {args['path']}")
        if not root.is_dir():
            return ToolResult(ok=False, error=f"Not a directory: {args['path']}")

        pattern = args.get("pattern")
        recursive = args.get("recursive", False)
        results: list[str] = []
        try:
            if recursive:
                iterator = root.rglob("*")
            else:
                iterator = root.iterdir()
            for entry in iterator:
                if entry.is_dir():
                    rel = entry.relative_to(root).as_posix()
                    name = rel + "/"
                else:
                    name = entry.relative_to(root).as_posix()
                if pattern and not fnmatch.fnmatch(entry.name, pattern):
                    continue
                results.append(name)
        except PermissionError as e:
            return ToolResult(ok=False, error=str(e))

        results.sort()
        if not results:
            return ToolResult(ok=True, output="(empty)")
        return ToolResult(ok=True, output="\n".join(results))
