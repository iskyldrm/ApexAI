"""ast_grep tool tests — uses Python's `ast` module as the parser.

We use Python's `ast` for a lightweight structural match. For multi-language
support (JS/Go/Rust) the real `ast-grep` binary would replace this.
"""
import ast
from pathlib import Path
from uuid import uuid4

import pytest

from app.agent.tools.ast_grep import AstGrepTool
from app.agent.tools.base import ToolContext


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


@pytest.fixture
def python_code(work_dir: str):
    root = Path(work_dir)
    (root / "a.py").write_text(
        "def foo():\n    return 1\n\n"
        "def bar():\n    return 2\n\n"
        "class Service:\n    def method(self):\n        return 3\n"
    )
    (root / "b.py").write_text("def baz():\n    return 4\n")


@pytest.mark.asyncio
async def test_finds_function_defs(ctx, python_code):
    tool = AstGrepTool()
    result = await tool.handler(ctx, {"pattern": "function_definition", "language": "python", "path": "."})
    assert result.ok
    # 3 function defs in a.py (foo, bar, method) + 1 in b.py (baz)
    assert "foo" in result.output
    assert "bar" in result.output
    assert "baz" in result.output
    assert "method" in result.output
    # Service is a class, not a function
    assert "Service" not in result.output


@pytest.mark.asyncio
async def test_finds_class_defs(ctx, python_code):
    tool = AstGrepTool()
    result = await tool.handler(ctx, {"pattern": "class_definition", "language": "python", "path": "."})
    assert result.ok
    assert "Service" in result.output


@pytest.mark.asyncio
async def test_no_matches(ctx, python_code):
    tool = AstGrepTool()
    result = await tool.handler(ctx, {"pattern": "import_statement", "language": "python", "path": "."})
    assert result.ok
    assert "no matches" in result.output.lower()


@pytest.mark.asyncio
async def test_unsupported_language_falls_back_to_grep(ctx, python_code):
    """For non-Python, fall back to plain text search."""
    tool = AstGrepTool()
    result = await tool.handler(ctx, {"pattern": "def foo", "language": "rust", "path": "a.py"})
    assert result.ok
    assert "def foo" in result.output


@pytest.mark.asyncio
async def test_path_traversal_blocked(ctx):
    tool = AstGrepTool()
    result = await tool.handler(ctx, {"pattern": "x", "language": "python", "path": "../../etc"})
    assert not result.ok


def test_ast_grep_metadata():
    tool = AstGrepTool()
    assert tool.name == "ast_grep"
    assert tool.is_mutating is False
