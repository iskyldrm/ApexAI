"""pytest adapter — runs Python tests and parses output."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.testing.runner import RunSpec, RunResult


class PythonAdapter:
    """Build pytest command + parse its summary line."""

    framework_name = "pytest"

    def __init__(self, spec: "RunSpec") -> None:
        self.spec = spec

    def build_command(self) -> list[str]:
        """Build the pytest command."""
        cmd = ["pytest"]
        if self.spec.test_filter:
            cmd += ["-k", self.spec.test_filter]
        cmd += ["-v", "--tb=short", "--no-header"]
        cmd += self.spec.extra_args
        return cmd

    def parse_output(
        self, stdout: str, stderr: str, exit_code: int
    ) -> "RunResult":
        """Parse pytest output into RunResult.

        Looks for the summary line:
            "5 passed, 2 failed, 1 skipped in 0.42s"
        Falls back to "passed" if exit_code == 0 and no summary found.
        """
        from app.testing.runner import RunResult

        text = stdout + "\n" + stderr
        # Match pytest summary. The line may look like:
        #   "5 passed, 2 failed, 1 skipped in 0.42s"
        #   "===== 5 passed, 2 failed, 1 skipped in 0.42s ====="
        #   "5 passed in 0.5s"
        #   "2 failed in 1.2s"
        # Approach: extract each count individually with a small regex.
        # Requires that BOTH a digit AND the word are present.
        count_re = re.compile(r"(\d+)\s+(passed|failed|skipped|errors?)\b")
        duration_re = re.compile(r"in\s+(\d+\.\d+)s")

        total = passed = failed = skipped = errors = 0
        duration_seconds = 0.0
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            # Look for any of the count words
            if not any(w in lower for w in ("passed", "failed", "error")):
                continue

            counts = count_re.findall(lower)
            if not counts:
                continue

            for n_str, word in counts:
                n = int(n_str)
                if word == "passed":
                    passed = n
                elif word == "failed":
                    failed = n
                elif word == "skipped":
                    skipped = n
                elif word in ("error", "errors"):
                    errors = n

            dm = duration_re.search(lower)
            if dm:
                try:
                    duration_seconds = float(dm.group(1))
                except (TypeError, ValueError):
                    pass

            # Only treat this line as the summary if it contains a
            # duration or "in Xs" (i.e. the final pytest line, not
            # an intermediate "2 failed" intermediate summary)
            if "in " not in lower:
                continue
            break

        total = passed + failed + skipped + errors

        if exit_code == 0 and failed == 0 and errors == 0 and total > 0:
            status = "passed"
        elif exit_code == 0 and total == 0:
            # No tests collected — that's an error in pytest
            status = "errored"
            errors = 1
        elif exit_code == 5:  # pytest exit code for "no tests collected"
            status = "errored"
            errors = 1
        else:
            status = "failed" if failed > 0 else "errored"

        return RunResult(
            status=status,
            framework=self.framework_name,
            language="python",
            image="",  # filled by runner
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            duration_ms=int(duration_seconds * 1000),
            exit_code=exit_code,
        )