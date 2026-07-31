"""vitest / jest adapter — runs Node tests and parses output."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.testing.runner import RunSpec, RunResult


class NodeAdapter:
    """Build vitest command + parse its summary.

    Supports vitest output format:
        "Test Files  3 passed (3)"
        "Tests       42 passed (42)"
    Also handles jest:
        "Tests: 42 passed, 2 failed, 1 skipped"
    """

    framework_name = "vitest"

    def __init__(self, spec: "RunSpec") -> None:
        self.spec = spec

    def build_command(self) -> list[str]:
        framework = self.spec.framework or "vitest"
        cmd = [framework]
        if framework == "vitest":
            cmd += ["run", "--reporter=default"]
        elif framework == "jest":
            cmd += ["--ci"]
        if self.spec.test_filter:
            cmd += ["-t", self.spec.test_filter]
        cmd += self.spec.extra_args
        return cmd

    def parse_output(
        self, stdout: str, stderr: str, exit_code: int
    ) -> "RunResult":
        from app.testing.runner import RunResult

        text = stdout + "\n" + stderr

        # Jest-style: "Tests: 42 passed, 2 failed, 1 skipped"
        jest_re = re.compile(
            r"Tests:\s*(?P<passed>\d+)\s+passed"
            r"(?:,\s*(?P<failed>\d+)\s+failed)?"
            r"(?:,\s*(?P<skipped>\d+)\s+skipped)?"
        )

        # vitest-style: "Tests       42 passed (42)"
        vitest_re = re.compile(
            r"Tests\s+(?P<passed>\d+)\s+passed"
            r"(?:.*?(?P<failed>\d+)\s+failed)?"
            r"(?:.*?(?P<skipped>\d+)\s+skipped)?"
        )

        passed = failed = skipped = errors = 0
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = jest_re.search(line)
            if m and m.group("passed"):
                passed = int(m.group("passed"))
                failed = int(m.group("failed") or 0)
                skipped = int(m.group("skipped") or 0)
                break
            m = vitest_re.search(line)
            if m and m.group("passed"):
                passed = int(m.group("passed"))
                failed = int(m.group("failed") or 0)
                skipped = int(m.group("skipped") or 0)
                break

        total = passed + failed + skipped
        if exit_code == 0 and failed == 0 and total > 0:
            status = "passed"
        elif exit_code == 0 and total == 0:
            status = "errored"
            errors = 1
        else:
            status = "failed" if failed > 0 else "errored"

        return RunResult(
            status=status,
            framework=self.framework_name,
            language="node",
            image="",
            total=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            exit_code=exit_code,
        )