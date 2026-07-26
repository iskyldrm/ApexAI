"""run_tests tool tests — wraps pytest with structured pass/fail summary."""
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.run_tests import RunTestsTool


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


@pytest.fixture
def ctx(work_dir):
    return ToolContext(agent_run_id=uuid4(), user_id="u1", org_id=None, work_dir=work_dir)


@pytest.fixture
def project_with_tests(work_dir):
    """A tiny project with pytest tests that pass + fail."""
    Path(work_dir, "test_sample.py").write_text(
        "def test_passes():\n    assert 1 + 1 == 2\n\n"
        "def test_fails():\n    assert 1 + 1 == 3\n"
    )
    # Ensure pytest is installed
    return work_dir


@pytest.mark.asyncio
async def test_runs_pytest_and_reports_results(ctx, project_with_tests):
    tool = RunTestsTool()
    result = await tool.handler(ctx, {"path": ".", "max_duration_seconds": 30})
    assert result.ok is False  # has failing test
    # Structured output mentions passes and failures
    assert "passed" in result.output.lower()
    assert "failed" in result.output.lower()
    assert "test_passes" in result.output or "1 passed" in result.output
    assert "test_fails" in result.output or "1 failed" in result.output
    # Metadata has counts
    assert "passed_count" in result.metadata
    assert "failed_count" in result.metadata


@pytest.mark.asyncio
async def test_all_passing_returns_ok(ctx, work_dir):
    Path(work_dir, "test_ok.py").write_text(
        "def test_a():\n    assert True\n\ndef test_b():\n    assert 1 == 1\n"
    )
    tool = RunTestsTool()
    result = await tool.handler(ctx, {"path": "test_ok.py", "max_duration_seconds": 30})
    assert result.ok
    assert "passed" in result.output.lower()


@pytest.mark.asyncio
async def test_no_tests_collected(ctx, work_dir):
    Path(work_dir, "empty.py").write_text("# nothing\n")
    tool = RunTestsTool()
    result = await tool.handler(ctx, {"path": "empty.py", "max_duration_seconds": 30})
    # No tests collected → ok with informative output
    assert "no tests ran" in result.output.lower() or "passed" in result.output.lower()


@pytest.mark.asyncio
async def test_specific_test_filter(ctx, project_with_tests):
    tool = RunTestsTool()
    result = await tool.handler(ctx, {"path": ".", "test_filter": "test_passes", "max_duration_seconds": 30})
    # Only the passing test runs
    assert "test_passes" in result.output or "1 passed" in result.output


@pytest.mark.asyncio
async def test_path_traversal_blocked(ctx):
    tool = RunTestsTool()
    result = await tool.handler(ctx, {"path": "../../etc"})
    assert not result.ok


def test_metadata():
    tool = RunTestsTool()
    assert tool.is_mutating is False  # tests are read-only
    assert tool.name == "run_tests"
    assert "commands:run" in tool.required_permissions
