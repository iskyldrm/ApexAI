"""apply_patch tool tests — atomic multi-file patch."""
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.apply_patch import ApplyPatchTool
from app.agent.tools.base import ToolContext


@pytest.fixture
def work_dir(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return str(d)


@pytest.fixture
def ctx(work_dir):
    return ToolContext(agent_run_id=uuid4(), user_id="u1", org_id=None, work_dir=work_dir)


@pytest.fixture
def multi_files(work_dir):
    """Two source files for cross-file patching."""
    Path(work_dir, "a.py").write_text("def foo():\n    return 1\n")
    Path(work_dir, "b.py").write_text("def bar():\n    return foo()\n")
    return work_dir


@pytest.mark.asyncio
async def test_edits_two_files_atomically(ctx, multi_files):
    tool = ApplyPatchTool()
    result = await tool.handler(ctx, {
        "patches": [
            {"path": "a.py", "old_text": "def foo():\n    return 1", "new_text": "def foo():\n    return 42"},
            {"path": "b.py", "old_text": "def bar():\n    return foo()", "new_text": "def bar():\n    return foo() * 2"},
        ]
    })
    assert result.ok
    a = Path(multi_files, "a.py").read_text()
    b = Path(multi_files, "b.py").read_text()
    assert "return 42" in a
    assert "* 2" in b


@pytest.mark.asyncio
async def test_rollback_when_one_file_fails(ctx, multi_files):
    tool = ApplyPatchTool()
    result = await tool.handler(ctx, {
        "patches": [
            {"path": "a.py", "old_text": "def foo():\n    return 1", "new_text": "def foo():\n    return 42"},
            {"path": "b.py", "old_text": "NONEXISTENT", "new_text": "x"},
        ]
    })
    assert not result.ok
    # a.py must NOT have been modified
    a = Path(multi_files, "a.py").read_text()
    assert "return 1" in a
    assert "return 42" not in a


@pytest.mark.asyncio
async def test_create_new_file_in_patch(ctx, work_dir):
    tool = ApplyPatchTool()
    result = await tool.handler(ctx, {
        "patches": [
            {"path": "new.py", "old_text": "", "new_text": "# new file\nprint('hi')\n"},
        ]
    })
    assert result.ok
    assert (Path(work_dir) / "new.py").exists()


@pytest.mark.asyncio
async def test_empty_patches_rejected(ctx):
    tool = ApplyPatchTool()
    result = await tool.handler(ctx, {"patches": []})
    assert not result.ok


@pytest.mark.asyncio
async def test_path_traversal_blocked(ctx, multi_files):
    tool = ApplyPatchTool()
    result = await tool.handler(ctx, {
        "patches": [{"path": "../../../etc/evil", "old_text": "x", "new_text": "y"}]
    })
    assert not result.ok


@pytest.mark.asyncio
async def test_missing_file_not_created_when_old_text_not_empty(ctx, work_dir):
    """If patching an existing file (old_text != ''), the file must exist."""
    tool = ApplyPatchTool()
    result = await tool.handler(ctx, {
        "patches": [
            {"path": "nope.py", "old_text": "def old():", "new_text": "def new():"},
        ]
    })
    assert not result.ok
    assert not (Path(work_dir) / "nope.py").exists()


def test_apply_patch_metadata():
    tool = ApplyPatchTool()
    assert tool.is_mutating is True
    assert tool.name == "apply_patch"
    assert "files:write" in tool.required_permissions
