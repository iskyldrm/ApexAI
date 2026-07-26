"""find_files tool — path-aware glob across work_dir.

Unlike list_dir(pattern=), this tool supports full glob patterns like
``src/services/*.py`` and ``**/*.test.ts``. Returns relative paths.
"""
from __future__ import annotations

from pathlib import Path

from app.agent.sandbox import SandboxError, safe_resolve_path
from app.agent.tools.base import Tool, ToolContext, ToolResult


class FindFilesTool(Tool):
    """Find files by path-aware glob pattern."""

    def __init__(self) -> None:
        super().__init__(
            name="find_files",
            description=(
                "Find files matching a path-aware glob pattern. Supports ** "
                "for any number of directories, * for filename wildcard. "
                "Examples: '*.py', 'src/services/*.py', '**/*.test.ts'."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 500},
                },
                "required": ["pattern"],
            },
            handler=self._run,
            is_mutating=False,
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        # Reject patterns that try to escape the work dir
        pattern = args["pattern"]
        if pattern.startswith("/") or ".." in pattern.split("/"):
            return ToolResult(ok=False, error=f"Pattern must be relative to work_dir, got {pattern!r}")

        try:
            # Resolve the literal part of the pattern to ensure it's inside work_dir
            literal_part = pattern.split("*", 1)[0].rstrip("/")
            if literal_part:
                safe_resolve_path(ctx.work_dir, literal_part, ctx.allowed_paths)
        except SandboxError as e:
            return ToolResult(ok=False, error=str(e))

        root = Path(ctx.work_dir)
        if not root.exists():
            return ToolResult(ok=False, error=f"work_dir not found: {ctx.work_dir}")

        max_results = args.get("max_results", 500)
        matches: list[str] = []
        # If pattern has no slash, treat it as basename glob across the whole tree
        iterator = root.rglob(pattern) if "/" not in pattern else root.glob(pattern)
        for path in iterator:
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = path.name
            matches.append(rel)
            if len(matches) >= max_results:
                break

        matches.sort()
        if not matches:
            return ToolResult(ok=True, output="(no matches)")
        out = "\n".join(matches)
        if len(matches) >= max_results:
            out += f"\n[truncated at {max_results} results]"
        return ToolResult(ok=True, output=out)
