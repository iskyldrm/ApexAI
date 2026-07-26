"""find_files tool tests — path-aware glob."""
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.find_files import FindFilesTool


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


@pytest.fixture
def ctx(work_dir):
    return ToolContext(agent_run_id=uuid4(), user_id="u1", org_id=None, work_dir=work_dir)


@pytest.fixture
def tree(work_dir):
    root = Path(work_dir)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("")
    (root / "src" / "util.py").write_text("")
    (root / "src" / "services").mkdir()
    (root / "src" / "services" / "users.py").write_text("")
    (root / "src" / "services" / "auth.py").write_text("")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("")
    (root / "README.md").write_text("")
    return work_dir


@pytest.mark.asyncio
async def test_finds_basename_glob(ctx, tree):
    tool = FindFilesTool()
    result = await tool.handler(ctx, {"pattern": "*.py"})
    assert result.ok
    assert "app.py" in result.output
    assert "util.py" in result.output


@pytest.mark.asyncio
async def test_finds_recursive_double_star(ctx, tree):
    tool = FindFilesTool()
    result = await tool.handler(ctx, {"pattern": "**/*.py"})
    assert result.ok
    for name in ("app.py", "util.py", "users.py", "auth.py", "test_app.py"):
        assert name in result.output


@pytest.mark.asyncio
async def test_finds_nested_path_glob(ctx, tree):
    tool = FindFilesTool()
    result = await tool.handler(ctx, {"pattern": "src/services/*.py"})
    assert result.ok
    assert "users.py" in result.output
    assert "auth.py" in result.output
    assert "app.py" not in result.output  # not in services/
    assert "test_app.py" not in result.output  # not in services/


@pytest.mark.asyncio
async def test_finds_double_star_nested(ctx, tree):
    tool = FindFilesTool()
    result = await tool.handler(ctx, {"pattern": "**/services/*.py"})
    assert result.ok
    assert "users.py" in result.output
    assert "auth.py" in result.output


@pytest.mark.asyncio
async def test_no_match_returns_empty(ctx, tree):
    tool = FindFilesTool()
    result = await tool.handler(ctx, {"pattern": "**/*.rs"})
    assert result.ok
    assert "(no matches)" in result.output or result.output.strip() == ""


@pytest.mark.asyncio
async def test_path_traversal_blocked(ctx):
    tool = FindFilesTool()
    result = await tool.handler(ctx, {"pattern": "../**/*"})
    assert not result.ok


@pytest.mark.asyncio
async def test_max_results_cap(ctx, tree):
    tool = FindFilesTool()
    result = await tool.handler(ctx, {"pattern": "**/*", "max_results": 2})
    assert result.ok
    # Should cap
    lines = [l for l in result.output.splitlines() if l.strip() and not l.startswith("[")]
    assert len(lines) <= 2


def test_find_files_metadata():
    tool = FindFilesTool()
    assert tool.is_mutating is False
    assert tool.name == "find_files"
