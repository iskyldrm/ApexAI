"""git_status tool — porcelain-style repo status."""
from __future__ import annotations

import asyncio

from app.agent.tools.base import Tool, ToolContext, ToolResult


class GitStatusTool(Tool):
    """Show working tree status (read-only)."""

    def __init__(self) -> None:
        super().__init__(
            name="git_status",
            description=(
                "Run `git status --porcelain --branch` in the work directory. "
                "Returns a clean summary. Read-only."
            ),
            parameters_schema={"type": "object", "properties": {}},
            handler=self._run,
            is_mutating=False,
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "status",
                "--porcelain",
                "--branch",
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
            return ToolResult(ok=False, error=err or f"git status failed (exit {proc.returncode})")

        out = stdout.decode("utf-8", errors="replace").strip()
        if not out:
            return ToolResult(ok=True, output="clean — nothing to commit, working tree clean")
        return ToolResult(ok=True, output=out)
