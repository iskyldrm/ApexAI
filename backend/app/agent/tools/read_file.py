"""read_file tool — read a file from the agent's work_dir."""
from __future__ import annotations

from pathlib import Path

from app.agent.sandbox import SandboxError, safe_resolve_path, truncate_output
from app.agent.tools.base import Tool, ToolContext, ToolResult


class ReadFileTool(Tool):
    """Read a UTF-8 text file. Supports line ranges and size cap."""

    def __init__(self) -> None:
        super().__init__(
            name="read_file",
            description=(
                "Read a file's contents. Returns UTF-8 text. "
                "Use start_line/end_line for partial reads, max_bytes to cap size. "
                "Refuses to read paths outside the work directory."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to work_dir"},
                    "start_line": {"type": "integer", "minimum": 0, "description": "1-indexed start"},
                    "end_line": {"type": "integer", "minimum": 1, "description": "Inclusive end"},
                    "max_bytes": {"type": "integer", "minimum": 100, "maximum": 1_000_000},
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

        path = Path(abs_path)
        if path.is_dir():
            return ToolResult(ok=False, error=f"{args['path']!r} is a directory")

        if not path.exists():
            return ToolResult(ok=False, error=f"File not found: {args['path']}")

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(ok=False, error="Binary file — read_file only supports UTF-8 text")

        lines = text.splitlines(keepends=True)
        start = args.get("start_line")
        end = args.get("end_line")
        if start is not None or end is not None:
            start_idx = (start - 1) if start else 0
            end_idx = end if end else len(lines)
            text = "".join(lines[start_idx:end_idx])

        max_bytes = args.get("max_bytes", 100_000)
        return ToolResult(ok=True, output=truncate_output(text, max_bytes))
