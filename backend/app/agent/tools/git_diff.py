"""git_diff tool — show working tree diff (read-only)."""
from __future__ import annotations

import asyncio

from app.agent.sandbox import truncate_output
from app.agent.tools.base import Tool, ToolContext, ToolResult


_MAX_DIFF_BYTES = 50_000


class GitDiffTool(Tool):
    """Show diff of unstaged changes (optionally filtered by path)."""

    def __init__(self) -> None:
        super().__init__(
            name="git_diff",
            description=(
                "Show `git diff` for the working tree. Optionally pass a path to "
                "limit to one file. Truncated to 50KB."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Limit diff to this path"},
                },
            },
            handler=self._run,
            is_mutating=False,
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        cmd = ["git", "diff"]
        if args.get("path"):
            cmd.extend(["--", args["path"]])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=ctx.work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            return ToolResult(ok=False, error="git not installed on system")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            if "not a git repository" in err:
                return ToolResult(ok=True, output="(not a git repository)")
            return ToolResult(ok=False, error=err or f"git diff failed (exit {proc.returncode})")

        out = stdout.decode("utf-8", errors="replace")
        if not out.strip():
            return ToolResult(ok=True, output="(no changes)")
        return ToolResult(ok=True, output=truncate_output(out, _MAX_DIFF_BYTES))
