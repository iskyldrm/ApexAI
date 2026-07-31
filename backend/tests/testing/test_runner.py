"""Tests for the build/test pipeline (Sub-System E)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from app.testing.adapters.node import NodeAdapter
from app.testing.adapters.python import PythonAdapter
from app.testing.flakiness import compute_flakiness
from app.testing.runner import (
    ContainerRunner,
    HostRunner,
    IMAGE_REGISTRY,
    RunSpec,
    get_default_runner,
)


# -------------------- Adapter parsing --------------------


def test_python_adapter_parses_passed_summary():
    a = PythonAdapter(RunSpec(language="python", project_path="/tmp/x"))
    result = a.parse_output(
        stdout="===== 5 passed, 2 failed, 1 skipped in 0.42s =====",
        stderr="",
        exit_code=1,
    )
    assert result.passed == 5
    assert result.failed == 2
    assert result.skipped == 1
    assert result.status == "failed"
    assert result.duration_ms == 420


def test_python_adapter_parses_all_passed():
    a = PythonAdapter(RunSpec(language="python", project_path="/tmp/x"))
    result = a.parse_output(
        stdout="===== 10 passed in 0.5s =====",
        stderr="",
        exit_code=0,
    )
    assert result.passed == 10
    assert result.failed == 0
    assert result.status == "passed"


def test_python_adapter_handles_no_tests():
    a = PythonAdapter(RunSpec(language="python", project_path="/tmp/x"))
    result = a.parse_output(
        stdout="no tests ran",
        stderr="",
        exit_code=5,  # pytest exit code for "no tests collected"
    )
    assert result.status == "errored"


def test_python_adapter_handles_zero_output():
    a = PythonAdapter(RunSpec(language="python", project_path="/tmp/x"))
    result = a.parse_output(stdout="", stderr="", exit_code=0)
    # No summary line → exit code 0 but no tests → errored
    assert result.status == "errored"


def test_python_adapter_build_command_includes_filter():
    a = PythonAdapter(RunSpec(language="python", project_path="/tmp/x", test_filter="important"))
    cmd = a.build_command()
    assert "-k" in cmd
    assert "important" in cmd


def test_node_adapter_parses_jest_summary():
    a = NodeAdapter(RunSpec(language="node", project_path="/tmp/x", framework="jest"))
    result = a.parse_output(
        stdout="Tests: 42 passed, 2 failed, 1 skipped",
        stderr="",
        exit_code=1,
    )
    assert result.passed == 42
    assert result.failed == 2
    assert result.skipped == 1
    assert result.status == "failed"


def test_node_adapter_parses_vitest_summary():
    a = NodeAdapter(RunSpec(language="node", project_path="/tmp/x"))
    result = a.parse_output(
        stdout="Test Files  3 passed (3)\nTests       42 passed (42)",
        stderr="",
        exit_code=0,
    )
    assert result.passed == 42
    assert result.status == "passed"


def test_node_adapter_handles_no_tests():
    a = NodeAdapter(RunSpec(language="node", project_path="/tmp/x"))
    result = a.parse_output(stdout="", stderr="", exit_code=1)
    assert result.status == "errored"


# -------------------- Image registry --------------------


def test_image_registry_has_four_languages():
    assert set(IMAGE_REGISTRY.keys()) == {"python", "node", "go", "rust"}


def test_image_registry_python_default():
    assert "python" in IMAGE_REGISTRY["python"]


# -------------------- Runner factory --------------------


def test_get_default_runner_returns_runner():
    runner = get_default_runner()
    # Either ContainerRunner or HostRunner — both have a .run() coroutine
    assert hasattr(runner, "run")


def test_container_runner_detects_docker(monkeypatch):
    """ContainerRunner.is_available returns True iff docker on PATH."""
    import shutil

    real_which = shutil.which

    def fake_which(name):
        if name == "docker":
            return "/usr/bin/docker"
        return real_which(name)

    monkeypatch.setattr(shutil, "which", fake_which)
    cr = ContainerRunner()
    cr._docker_available = None  # force re-check
    assert cr.is_available() is True


def test_container_runner_no_docker(monkeypatch):
    import shutil

    real_which = shutil.which

    def fake_which(name):
        return None  # simulate no docker

    monkeypatch.setattr(shutil, "which", fake_which)
    cr = ContainerRunner()
    cr._docker_available = None
    assert cr.is_available() is False


# -------------------- Host runner integration --------------------


@pytest.mark.asyncio
async def test_host_runner_runs_real_pytest(tmp_path):
    """A tiny pytest that always passes."""
    test_file = tmp_path / "test_pass.py"
    test_file.write_text("def test_pass(): assert True\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths=.\n")

    runner = HostRunner()
    spec = RunSpec(
        language="python",
        project_path=str(tmp_path),
        timeout_seconds=30,
    )
    result = await runner.run(spec)
    assert result.status == "passed"
    assert result.passed >= 1
    assert result.failed == 0


@pytest.mark.asyncio
async def test_host_runner_runs_failing_pytest(tmp_path):
    test_file = tmp_path / "test_fail.py"
    test_file.write_text("def test_fail(): assert False\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths=.\n")

    runner = HostRunner()
    spec = RunSpec(
        language="python",
        project_path=str(tmp_path),
        timeout_seconds=30,
    )
    result = await runner.run(spec)
    assert result.status == "failed"
    assert result.failed >= 1


@pytest.mark.asyncio
async def test_host_runner_handles_missing_test_file(tmp_path):
    """Empty directory → pytest exit 5 (no tests) → errored."""
    runner = HostRunner()
    spec = RunSpec(language="python", project_path=str(tmp_path), timeout_seconds=15)
    result = await runner.run(spec)
    # Either 'errored' (exit 5) or 'failed' depending on pytest version
    assert result.status in ("errored", "failed")


@pytest.mark.asyncio
async def test_host_runner_respects_timeout(tmp_path):
    """A test that sleeps longer than the timeout → status='timeout'."""
    test_file = tmp_path / "test_slow.py"
    test_file.write_text(
        "import time\ndef test_slow(): time.sleep(5)\n"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths=.\n")

    runner = HostRunner()
    spec = RunSpec(
        language="python",
        project_path=str(tmp_path),
        timeout_seconds=1,  # 1s, less than the 5s sleep
    )
    result = await runner.run(spec)
    assert result.status == "timeout"


# -------------------- Service + flakiness --------------------


@pytest.mark.asyncio
async def test_service_creates_test_run_row(tmp_path):
    """Service persists a TestRun row + summary."""
    from app.db import async_session_maker
    from app.models.testing import TestRun
    from app.testing.service import TestRunService

    test_file = tmp_path / "test_x.py"
    test_file.write_text("def test_ok(): assert True\n")
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths=.\n")

    runner = HostRunner()
    service = TestRunService(runner=runner)

    async with async_session_maker() as session:
        test_run = await service.run(
            session,
            RunSpec(language="python", project_path=str(tmp_path), timeout_seconds=30),
        )
        assert test_run.id is not None
        assert test_run.status == "passed"
        assert test_run.passed >= 1


@pytest.mark.asyncio
async def test_flakiness_detects_flaky_test(tmp_path):
    """A test that passes once and fails once is flaky."""
    from uuid import uuid4

    from app.db import async_session_maker
    from app.models.testing import TestRun, TestRunRecord

    test_name = f"tests/test_flaky_{uuid4().hex[:6]}.py::test_x"

    async with async_session_maker() as session:
        # Create two runs: one pass, one fail for the same test
        for status in ("passed", "failed"):
            run = TestRun(
                project_path=str(tmp_path),
                language="python",
                framework="pytest",
                status="failed" if status == "failed" else "passed",
                total=1,
                passed=1 if status == "passed" else 0,
                failed=1 if status == "failed" else 0,
            )
            session.add(run)
            await session.flush()
            rec = TestRunRecord(
                test_run_id=run.id,
                test_name=test_name,
                status=status,
                duration_ms=10,
            )
            session.add(rec)
            await session.commit()

        # Now compute flakiness
        report = await compute_flakiness(session)
        flaky_names = {t["test_name"] for t in report.flaky_tests}
        assert test_name in flaky_names