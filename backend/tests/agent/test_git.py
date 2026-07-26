"""git_status + git_diff tool tests."""
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.git_diff import GitDiffTool
from app.agent.tools.git_status import GitStatusTool


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@apex.ai"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


@pytest.fixture
def git_work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    _init_repo(d)
    return str(d)


@pytest.fixture
def ctx(git_work_dir):
    return ToolContext(agent_run_id=uuid4(), user_id="u1", org_id=None, work_dir=git_work_dir)


# -------------------- git_status --------------------


@pytest.mark.asyncio
async def test_clean_repo_reports_clean(ctx):
    tool = GitStatusTool()
    result = await tool.handler(ctx, {})
    assert result.ok
    # Clean repo → only the branch line, no file status entries
    lines = [l for l in result.output.splitlines() if l.strip()]
    assert all(l.startswith("##") for l in lines), f"unexpected file entries: {result.output}"


@pytest.mark.asyncio
async def test_untracked_file_shown(ctx, git_work_dir):
    (Path(git_work_dir) / "new.py").write_text("x = 1\n")
    tool = GitStatusTool()
    result = await tool.handler(ctx, {})
    assert result.ok
    assert "new.py" in result.output


@pytest.mark.asyncio
async def test_modified_file_shown(ctx, git_work_dir):
    (Path(git_work_dir) / "README.md").write_text("modified content\n")
    tool = GitStatusTool()
    result = await tool.handler(ctx, {})
    assert result.ok
    assert "README.md" in result.output


def test_git_status_metadata():
    tool = GitStatusTool()
    assert tool.is_mutating is False
    assert tool.name == "git_status"


# -------------------- git_diff --------------------


@pytest.mark.asyncio
async def test_diff_no_changes(ctx):
    tool = GitDiffTool()
    result = await tool.handler(ctx, {})
    assert result.ok
    assert result.output.strip() == "" or "no changes" in result.output.lower()


@pytest.mark.asyncio
async def test_diff_modified_file(ctx, git_work_dir):
    (Path(git_work_dir) / "README.md").write_text("modified content\n")
    tool = GitDiffTool()
    result = await tool.handler(ctx, {"path": "README.md"})
    assert result.ok
    assert "modified content" in result.output
    assert "-hi" in result.output or "---" in result.output


@pytest.mark.asyncio
async def test_diff_truncates_huge_diff(ctx, git_work_dir):
    (Path(git_work_dir) / "big.txt").write_text("y" * 200_000)
    tool = GitDiffTool()
    result = await tool.handler(ctx, {"path": "big.txt"})
    assert result.ok
    assert len(result.output) < 200_000


def test_git_diff_metadata():
    tool = GitDiffTool()
    assert tool.is_mutating is False
    assert tool.name == "git_diff"
