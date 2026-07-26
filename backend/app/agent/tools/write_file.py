"""write_file tool — create or overwrite a file with the 50% reject rule.

ApexAITeam pattern: when an existing file would be overwritten with much less
content, the LLM is probably trying to do a search-replace — refuse and tell
it to use edit_file instead. The 50% threshold is configurable.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.agent.sandbox import SandboxError, safe_resolve_path
from app.agent.tools.base import Tool, ToolContext, ToolResult


_REJECT_RATIO = 0.5  # new content must be ≥ 50% of existing to overwrite


class WriteFileTool(Tool):
    """Write a file. Refuses to shrink an existing file by more than 50%."""

    # Per-agent-run record of files the agent has explicitly chosen to write.
    intentional_files: dict[UUID, set[str]] = {}

    def __init__(self) -> None:
        super().__init__(
            name="write_file",
            description=(
                "Write content to a file, creating parent directories as needed. "
                "If the file already exists and the new content is less than 50% of "
                "the existing size, this tool refuses and asks you to use edit_file "
                "instead. Use this for NEW files or for near-complete rewrites."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to work_dir"},
                    "content": {"type": "string", "description": "File contents"},
                },
                "required": ["path", "content"],
            },
            handler=self._run,
            is_mutating=True,
            required_permissions=("files:write",),
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        try:
            abs_path = safe_resolve_path(ctx.work_dir, args["path"], ctx.allowed_paths)
        except SandboxError as e:
            return ToolResult(ok=False, error=str(e))

        target = Path(abs_path)
        new_content = args["content"]

        if target.exists():
            try:
                existing = target.read_text(encoding="utf-8")
            except OSError as e:
                return ToolResult(ok=False, error=f"Could not read existing file: {e}")
            if len(existing) > 0:
                ratio = len(new_content) / len(existing)
                if ratio < _REJECT_RATIO:
                    return ToolResult(
                        ok=False,
                        error=(
                            f"Refusing to shrink file: new content is {ratio:.0%} of existing "
                            f"({len(new_content)} vs {len(existing)} bytes). "
                            f"Use edit_file for targeted changes."
                        ),
                    )

        # Create parent dirs
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")

        # Record intentional file
        self.intentional_files.setdefault(ctx.agent_run_id, set()).add(args["path"])

        return ToolResult(
            ok=True,
            output=f"Wrote {len(new_content)} bytes to {args['path']}",
            metadata={"intentional": True, "path": args["path"]},
        )
