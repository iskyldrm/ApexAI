"""run_tests tool — invoke pytest with structured pass/fail output.

Runs ``pytest -v --tb=short`` in the agent's work_dir and parses the summary
line (``= X passed, Y failed in Zs =``) to return a structured ToolResult.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

from app.agent.sandbox import SandboxError, safe_resolve_path
from app.agent.tools.base import Tool, ToolContext, ToolResult


_SUMMARY_RE = re.compile(
    r"=+\s*(?P<summary>.+?)\s*in\s+(?P<duration>[\d.]+)s?\s*=+",
    re.DOTALL,
)
_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+failed")
_ERRORS_RE = re.compile(r"(\d+)\s+errors")
_SKIPPED_RE = re.compile(r"(\d+)\s+skipped")


class RunTestsTool(Tool):
    """Run pytest with structured output."""

    def __init__(self) -> None:
        super().__init__(
            name="run_tests",
            description=(
                "Run pytest in the work directory and return a structured summary "
                "of passed/failed/errored tests. Optionally filter by path or "
                "test name pattern. Read-only — does not modify code."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory to test", "default": "."},
                    "test_filter": {"type": "string", "description": "pytest -k expression"},
                    "max_duration_seconds": {"type": "integer", "minimum": 1, "maximum": 600, "default": 120},
                },
            },
            handler=self._run,
            is_mutating=False,
            required_permissions=("commands:run",),
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        try:
            abs_path = safe_resolve_path(ctx.work_dir, args.get("path", "."), ctx.allowed_paths)
        except SandboxError as e:
            return ToolResult(ok=False, error=str(e))

        if not Path(abs_path).exists():
            return ToolResult(ok=False, error=f"Path not found: {args.get('path', '.')}")

        cmd = ["pytest", "-v", "--tb=short", "--no-header"]
        cmd.append(abs_path)
        if args.get("test_filter"):
            cmd.extend(["-k", args["test_filter"]])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=ctx.work_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=args.get("max_duration_seconds", 120)
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    ok=False,
                    error=f"Tests timed out after {args.get('max_duration_seconds', 120)}s",
                )
        except FileNotFoundError:
            return ToolResult(ok=False, error="pytest not installed in this environment")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

        output = stdout.decode("utf-8", errors="replace")
        # Truncate to last 50KB
        if len(output) > 50_000:
            output = "...[truncated]...\n" + output[-50_000:]

        passed = _first_int(_PASSED_RE.findall(output))
        failed = _first_int(_FAILED_RE.findall(output))
        errors = _first_int(_ERRORS_RE.findall(output))
        skipped = _first_int(_SKIPPED_RE.findall(output))

        # If no tests ran, the output is short and exit code is 5
        if proc.returncode == 5:
            return ToolResult(
                ok=True,
                output=output + "\n(no tests ran)",
                metadata={"passed_count": 0, "failed_count": 0, "skipped_count": 0, "no_tests_ran": True},
            )

        all_passing = failed == 0 and errors == 0 and passed > 0
        return ToolResult(
            ok=all_passing,
            output=output,
            error=None if all_passing else f"{failed} test(s) failed, {errors} errored",
            metadata={
                "passed_count": passed,
                "failed_count": failed,
                "error_count": errors,
                "skipped_count": skipped,
                "exit_code": proc.returncode,
            },
        )


def _first_int(matches: list[str]) -> int:
    return int(matches[0]) if matches else 0
