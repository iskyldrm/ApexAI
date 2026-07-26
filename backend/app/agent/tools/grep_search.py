"""grep_search tool — content search across the work_dir.

Uses Python's own regex engine (no external ripgrep dependency) — sufficient
for the dev/single-pod scale; ripgrep would be faster for huge repos but
adds a system dep we don't yet need in the agent loop.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.agent.sandbox import SandboxError, safe_resolve_path, truncate_output
from app.agent.tools.base import Tool, ToolContext, ToolResult


_SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__", "dist", "build", ".next"})


class GrepSearchTool(Tool):
    """Regex content search with optional file glob + context lines."""

    def __init__(self) -> None:
        super().__init__(
            name="grep_search",
            description=(
                "Search for a regex pattern in files under a path. Returns matches "
                "in 'file:line:content' format. Skips common build/cache dirs."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regex pattern"},
                    "path": {"type": "string", "description": "Root path to search"},
                    "include_glob": {"type": "string", "description": "File glob, e.g. '*.py'"},
                    "context_lines": {"type": "integer", "minimum": 0, "maximum": 10, "default": 0},
                    "max_matches": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
                },
                "required": ["pattern", "path"],
            },
            handler=self._run,
            is_mutating=False,
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        try:
            abs_path = safe_resolve_path(ctx.work_dir, args["path"], ctx.allowed_paths)
        except SandboxError as e:
            return ToolResult(ok=False, error=str(e))

        try:
            regex = re.compile(args["pattern"])
        except re.error as e:
            return ToolResult(ok=False, error=f"Invalid regex: {e}")

        include_glob = args.get("include_glob")
        context = args.get("context_lines", 0)
        max_matches = args.get("max_matches", 100)
        root = Path(abs_path)
        if not root.exists():
            return ToolResult(ok=False, error=f"Path not found: {args['path']}")

        files = (
            [p for p in root.rglob("*") if p.is_file()]
            if root.is_dir()
            else [root]
        )

        matches: list[str] = []
        for file_path in files:
            # Skip excluded dirs
            if any(part in _SKIP_DIRS for part in file_path.parts):
                continue
            if include_glob and not _glob_match(file_path.name, include_glob):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if regex.search(line):
                    rel = file_path.relative_to(ctx.work_dir) if str(file_path).startswith(ctx.work_dir) else file_path.name
                    if context:
                        start = max(0, i - context)
                        end = min(len(lines), i + context + 1)
                        snippet = "\n".join(
                            f"{rel}:{j + 1}:{lines[j]}" for j in range(start, end)
                        )
                        matches.append(snippet)
                    else:
                        matches.append(f"{rel}:{i + 1}:{line}")
                    if len(matches) >= max_matches:
                        return ToolResult(
                            ok=True,
                            output=truncate_output("\n".join(matches)) + f"\n[truncated at {max_matches} matches]",
                        )

        if not matches:
            return ToolResult(ok=True, output="(no matches)")
        return ToolResult(ok=True, output=truncate_output("\n".join(matches)))


def _glob_match(name: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(name, pattern)
