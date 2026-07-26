"""edit_file tool tests — search-replace engine."""
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.edit_file import EditFileTool


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


@pytest.fixture
def ctx(work_dir):
    return ToolContext(agent_run_id=uuid4(), user_id="u1", org_id=None, work_dir=work_dir)


@pytest.fixture
def hello_py(work_dir):
    Path(work_dir, "hello.py").write_text(
        "def greet(name):\n    return f'hello {name}'\n\n"
        "if __name__ == '__main__':\n    print(greet('world'))\n"
    )
    return work_dir


@pytest.mark.asyncio
async def test_single_edit_replaces_text(ctx, hello_py):
    tool = EditFileTool()
    result = await tool.handler(ctx, {
        "path": "hello.py",
        "edits": [
            {"old_text": "def greet(name):", "new_text": "def greet(name: str):"}
        ],
    })
    assert result.ok
    content = Path(hello_py, "hello.py").read_text()
    assert "def greet(name: str):" in content
    assert "def greet(name):" not in content


@pytest.mark.asyncio
async def test_multiple_edits_atomic(ctx, hello_py):
    tool = EditFileTool()
    result = await tool.handler(ctx, {
        "path": "hello.py",
        "edits": [
            {"old_text": "def greet(name):", "new_text": "def greet(name: str):"},
            {"old_text": "print(greet('world'))", "new_text": "print(greet('Earth'))"},
        ],
    })
    assert result.ok
    content = Path(hello_py, "hello.py").read_text()
    assert "name: str" in content
    assert "Earth" in content


@pytest.mark.asyncio
async def test_edit_block_not_found_returns_error(ctx, hello_py):
    tool = EditFileTool()
    result = await tool.handler(ctx, {
        "path": "hello.py",
        "edits": [{"old_text": "NONEXISTENT_TEXT", "new_text": "x"}],
    })
    assert not result.ok
    assert "not found" in (result.error or "").lower()
    # File must be unchanged
    assert "def greet(name):" in Path(hello_py, "hello.py").read_text()


@pytest.mark.asyncio
async def test_edit_atomic_one_fails_rolls_back_all(ctx, hello_py):
    tool = EditFileTool()
    result = await tool.handler(ctx, {
        "path": "hello.py",
        "edits": [
            {"old_text": "def greet(name):", "new_text": "def greet(name: str):"},
            {"old_text": "NOT_THERE", "new_text": "x"},
        ],
    })
    assert not result.ok
    # First edit should not have been applied
    assert "def greet(name):" in Path(hello_py, "hello.py").read_text()
    assert "name: str" not in Path(hello_py, "hello.py").read_text()


@pytest.mark.asyncio
async def test_whitespace_normalized_match(ctx, hello_py):
    tool = EditFileTool()
    # File has single-space indent, agent sends with extra spaces
    result = await tool.handler(ctx, {
        "path": "hello.py",
        "edits": [
            {"old_text": "def greet(name):\n    return f'hello {name}'",
             "new_text": "def greet(name: str) -> str:\n    return f'hi {name}'"}
        ],
    })
    assert result.ok


@pytest.mark.asyncio
async def test_path_traversal_blocked(ctx):
    tool = EditFileTool()
    result = await tool.handler(ctx, {
        "path": "../../../etc/passwd",
        "edits": [{"old_text": "x", "new_text": "y"}],
    })
    assert not result.ok


@pytest.mark.asyncio
async def test_missing_file_returns_error(ctx):
    tool = EditFileTool()
    result = await tool.handler(ctx, {
        "path": "nope.py",
        "edits": [{"old_text": "x", "new_text": "y"}],
    })
    assert not result.ok


def test_edit_file_metadata():
    tool = EditFileTool()
    assert tool.is_mutating is True
    assert "files:write" in tool.required_permissions
    assert tool.name == "edit_file"
