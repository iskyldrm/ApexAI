"""list_dir + grep_search tool tests."""
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.grep_search import GrepSearchTool
from app.agent.tools.list_dir import ListDirTool


@pytest.fixture
def work_dir(tmp_path: Path) -> str:
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


@pytest.fixture
def populated(work_dir: str) -> str:
    """Create a small project tree for grep/list tests."""
    root = Path(work_dir)
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def hello():\n    return 'world'\n")
    (root / "src" / "util.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "README.md").write_text("# project\n")
    (root / ".hidden").write_text("hidden file")
    (root / "src" / "tests").mkdir()
    (root / "src" / "tests" / "test_app.py").write_text("from app import hello\n")
    return work_dir


@pytest.fixture
def ctx(work_dir: str) -> ToolContext:
    return ToolContext(
        agent_run_id=uuid4(),
        user_id="u1",
        org_id=None,
        work_dir=work_dir,
    )


# -------------------- list_dir --------------------


@pytest.mark.asyncio
async def test_list_dir_top_level(ctx, populated):
    tool = ListDirTool()
    result = await tool.handler(ctx, {"path": "."})
    assert result.ok
    # Top-level: src, README.md, .hidden
    for name in ("src", "README.md", ".hidden"):
        assert name in result.output


@pytest.mark.asyncio
async def test_list_dir_recursive(ctx, populated):
    tool = ListDirTool()
    result = await tool.handler(ctx, {"path": ".", "recursive": True})
    assert result.ok
    for name in ("app.py", "util.py", "test_app.py"):
        assert name in result.output


@pytest.mark.asyncio
async def test_list_dir_glob_pattern(ctx, populated):
    tool = ListDirTool()
    result = await tool.handler(ctx, {"path": "src", "pattern": "*.py"})
    assert result.ok
    assert "app.py" in result.output
    assert "util.py" in result.output
    assert "test_app.py" not in result.output  # in subdir


@pytest.mark.asyncio
async def test_list_dir_missing_path(ctx):
    tool = ListDirTool()
    result = await tool.handler(ctx, {"path": "nope"})
    assert not result.ok


@pytest.mark.asyncio
async def test_list_dir_path_traversal_blocked(ctx):
    tool = ListDirTool()
    result = await tool.handler(ctx, {"path": "../../../etc"})
    assert not result.ok


def test_list_dir_metadata():
    tool = ListDirTool()
    assert tool.name == "list_dir"
    assert tool.is_mutating is False


# -------------------- grep_search --------------------


@pytest.mark.asyncio
async def test_grep_search_finds_match(ctx, populated):
    tool = GrepSearchTool()
    result = await tool.handler(ctx, {"pattern": "def hello", "path": "."})
    assert result.ok
    assert "app.py" in result.output
    assert "def hello" in result.output


@pytest.mark.asyncio
async def test_grep_search_no_match(ctx, populated):
    tool = GrepSearchTool()
    result = await tool.handler(ctx, {"pattern": "NONEXISTENT_TOKEN_XYZ", "path": "."})
    assert result.ok
    assert "no matches" in result.output.lower() or result.output.strip() == ""


@pytest.mark.asyncio
async def test_grep_search_include_glob(ctx, populated):
    tool = GrepSearchTool()
    result = await tool.handler(ctx, {
        "pattern": "hello",
        "path": "src",
        "include_glob": "*.py",
    })
    assert result.ok
    # Should find the call site in test_app.py
    assert "test_app.py" in result.output or "app.py" in result.output


@pytest.mark.asyncio
async def test_grep_search_path_traversal_blocked(ctx):
    tool = GrepSearchTool()
    result = await tool.handler(ctx, {"pattern": "anything", "path": "../../../etc"})
    assert not result.ok


@pytest.mark.asyncio
async def test_grep_search_context_lines(ctx, populated):
    tool = GrepSearchTool()
    result = await tool.handler(ctx, {
        "pattern": "return",
        "path": "src",
        "context_lines": 1,
    })
    assert result.ok
    # The line above 'return a + b' should be 'def add(a, b):'
    assert "def add" in result.output


def test_grep_search_metadata():
    tool = GrepSearchTool()
    assert tool.name == "grep_search"
    assert tool.is_mutating is False
