"""read_file tool tests."""
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.base import ToolContext, ToolResult
from app.agent.tools.read_file import ReadFileTool
from app.agent.roles import Role


@pytest.fixture
def work_dir(tmp_path: Path) -> str:
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


@pytest.fixture
def ctx(work_dir: str) -> ToolContext:
    return ToolContext(
        agent_run_id=uuid4(),
        user_id="u1",
        org_id=None,
        work_dir=work_dir,
    )


@pytest.mark.asyncio
async def test_reads_existing_file(ctx, work_dir):
    Path(work_dir, "hello.txt").write_text("hello world\n")
    tool = ReadFileTool()
    result = await tool.handler(ctx, {"path": "hello.txt"})
    assert result.ok
    assert result.output == "hello world\n"


@pytest.mark.asyncio
async def test_file_not_found_returns_error(ctx):
    tool = ReadFileTool()
    result = await tool.handler(ctx, {"path": "missing.txt"})
    assert not result.ok
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_path_traversal_blocked(ctx, work_dir):
    """Agent can't read /etc/passwd via ../."""
    tool = ReadFileTool()
    result = await tool.handler(ctx, {"path": "../../../../etc/passwd"})
    assert not result.ok
    assert "escape" in (result.error or "").lower() or "allowed" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_truncates_large_file(ctx, work_dir):
    Path(work_dir, "big.txt").write_text("x" * 200_000)
    tool = ReadFileTool()
    result = await tool.handler(ctx, {"path": "big.txt", "max_bytes": 1024})
    assert result.ok
    assert len(result.output) < 200_000
    assert "truncated" in result.output


@pytest.mark.asyncio
async def test_line_range(ctx, work_dir):
    Path(work_dir, "lines.txt").write_text("\n".join(f"line{i}" for i in range(50)))
    tool = ReadFileTool()
    # File has "line0" through "line49". 1-indexed: line 10 = "line9".
    result = await tool.handler(ctx, {"path": "lines.txt", "start_line": 10, "end_line": 12})
    assert result.ok
    assert "line9" in result.output
    assert "line10" in result.output
    assert "line11" in result.output
    assert "line8" not in result.output
    assert "line12" not in result.output


@pytest.mark.asyncio
async def test_directory_returns_error(ctx, work_dir):
    sub = Path(work_dir, "subdir")
    sub.mkdir()
    tool = ReadFileTool()
    result = await tool.handler(ctx, {"path": "subdir"})
    assert not result.ok
    assert "directory" in (result.error or "").lower()


def test_read_file_metadata():
    tool = ReadFileTool()
    assert tool.name == "read_file"
    assert tool.is_mutating is False
    assert tool.required_permissions == ()
    # All roles should be allowed (no role_visibility filter)
    assert tool.role_visibility == ()


def test_openai_schema():
    tool = ReadFileTool()
    schema = tool.to_openai_schema()
    fn = schema["function"]
    assert fn["name"] == "read_file"
    assert "path" in fn["parameters"]["properties"]
