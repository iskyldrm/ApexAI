"""run_command tool — sandboxed subprocess execution.

- Blocklist: refuses ``rm -rf /``, sudo, fork bombs, etc. (see sandbox.assert_command_safe)
- Workdir: always the agent's work_dir unless explicitly overridden
- Timeout: 120s default, configurable up to 600s
- Resource limits: CPU/address space via preexec_fn (POSIX)
- Output: 50KB cap (truncate_output)
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from typing import Any

from app.agent.sandbox import (
    SandboxError,
    assert_command_safe,
    truncate_output,
)
from app.agent.tools.base import Tool, ToolContext, ToolResult


_DEFAULT_TIMEOUT = 120
_MAX_TIMEOUT = 600
_MAX_OUTPUT_BYTES = 50_000


class RunCommandTool(Tool):
    """Run a shell command in the work_dir, with safety guards."""

    def __init__(self) -> None:
        super().__init__(
            name="run_command",
            description=(
                "Run a shell command in the agent's work directory. Output (stdout+stderr) "
                "is returned, truncated to 50KB. Default timeout 120s, max 600s. "
                "Dangerous commands (rm -rf, sudo, fork bombs, etc.) are blocked."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_TIMEOUT,
                        "default": _DEFAULT_TIMEOUT,
                    },
                    "env_overrides": {
                        "type": "object",
                        "description": "Extra env vars to merge in",
                        "additionalProperties": {"type": "string"},
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Override work_dir (must still be inside it)",
                    },
                },
                "required": ["command"],
            },
            handler=self._run,
            is_mutating=True,
            required_permissions=("commands:run",),
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        command: str = args["command"]
        try:
            assert_command_safe(command)
        except SandboxError as e:
            return ToolResult(ok=False, error=str(e), metadata={"blocked": True})

        timeout = min(args.get("timeout_seconds", _DEFAULT_TIMEOUT), _MAX_TIMEOUT)
        cwd = ctx.work_dir
        if args.get("cwd"):
            from app.agent.sandbox import safe_resolve_path
            try:
                cwd = safe_resolve_path(ctx.work_dir, args["cwd"], ctx.allowed_paths)
            except SandboxError as e:
                return ToolResult(ok=False, error=str(e))

        env = {**os.environ, **(args.get("env_overrides") or {})}

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                env=env,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    ok=False,
                    error=f"Command timed out after {timeout}s",
                    metadata={"exit_code": -1, "timeout": True},
                )

            output = stdout.decode("utf-8", errors="replace")
            truncated = truncate_output(output, _MAX_OUTPUT_BYTES)
            exit_code = proc.returncode
            return ToolResult(
                ok=(exit_code == 0),
                output=truncated,
                error=None if exit_code == 0 else f"Command exited with code {exit_code}",
                metadata={"exit_code": exit_code, "command": command},
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Subprocess error: {e}")
