"""write_file tool tests — covers intentionalFiles + 50% reject logic."""
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.write_file import WriteFileTool


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


@pytest.fixture
def ctx(work_dir):
    return ToolContext(agent_run_id=uuid4(), user_id="u1", org_id=None, work_dir=work_dir)


@pytest.mark.asyncio
async def test_create_new_file(ctx, work_dir):
    tool = WriteFileTool()
    result = await tool.handler(ctx, {"path": "new.py", "content": "print('hi')\n"})
    assert result.ok
    assert (Path(work_dir) / "new.py").read_text() == "print('hi')\n"
    assert result.metadata["intentional"] is True


@pytest.mark.asyncio
async def test_overwrite_near_full_allowed(ctx, work_dir):
    """If new content ≥ 50% of existing, allow overwrite."""
    Path(work_dir, "f.py").write_text("a" * 1000)
    tool = WriteFileTool()
    # 800/1000 = 0.8 → above 0.5 → allowed
    result = await tool.handler(ctx, {"path": "f.py", "content": "a" * 800})
    assert result.ok
    assert (Path(work_dir) / "f.py").read_text() == "a" * 800


@pytest.mark.asyncio
async def test_overwrite_large_existing_rejected(ctx, work_dir):
    """If new content < 50% of existing, reject and tell agent to use edit_file."""
    Path(work_dir, "f.py").write_text("a" * 10_000)
    tool = WriteFileTool()
    result = await tool.handler(ctx, {"path": "f.py", "content": "a" * 100})  # 1% ratio
    # Note: with content 100 vs existing 10_000, ratio is 0.01 → below 0.5 → reject
    assert not result.ok
    assert "edit_file" in (result.error or "")


@pytest.mark.asyncio
async def test_overwrite_when_ratio_above_threshold_allowed(ctx, work_dir):
    Path(work_dir, "f.py").write_text("a" * 1000)
    tool = WriteFileTool()
    # 800/1000 = 0.8 → above 0.5
    result = await tool.handler(ctx, {"path": "f.py", "content": "a" * 800})
    assert result.ok


@pytest.mark.asyncio
async def test_path_traversal_blocked(ctx):
    tool = WriteFileTool()
    result = await tool.handler(ctx, {"path": "../../../tmp/evil.py", "content": "x"})
    assert not result.ok


@pytest.mark.asyncio
async def test_creates_parent_dirs(ctx, work_dir):
    tool = WriteFileTool()
    result = await tool.handler(ctx, {"path": "deep/nested/file.py", "content": "x"})
    assert result.ok
    assert (Path(work_dir) / "deep" / "nested" / "file.py").exists()


@pytest.mark.asyncio
async def test_is_mutating_and_requires_permission():
    tool = WriteFileTool()
    assert tool.is_mutating is True
    assert "files:write" in tool.required_permissions


def test_intentional_files_recorded_in_metadata(ctx, work_dir):
    tool = WriteFileTool()
    import asyncio
    asyncio.run(tool.handler(ctx, {"path": "a.py", "content": "x"}))
    assert "a.py" in tool.intentional_files.get(ctx.agent_run_id, set())
