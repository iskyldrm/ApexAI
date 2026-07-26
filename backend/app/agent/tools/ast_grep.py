"""ast_grep tool — structural code search.

Python is parsed via the stdlib ``ast`` module. Other languages fall back to
plain text matching. When the real ``ast-grep`` CLI is available, swap
``_python_match`` for a subprocess call.
"""
from __future__ import annotations

import ast
from pathlib import Path

from app.agent.sandbox import SandboxError, safe_resolve_path, truncate_output
from app.agent.tools.base import Tool, ToolContext, ToolResult


class AstGrepTool(Tool):
    """Structural code search by AST node type (Python) or text (other)."""

    def __init__(self) -> None:
        super().__init__(
            name="ast_grep",
            description=(
                "Find code structures by AST node type. Currently supports Python "
                "via the `ast` module (function_definition, class_definition, "
                "import_statement, etc.). Other languages fall back to literal "
                "text search."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "AST node type (Python) or text pattern (other)",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript", "typescript", "go", "rust"],
                        "default": "python",
                    },
                    "path": {"type": "string", "description": "File or directory"},
                },
                "required": ["pattern"],
            },
            handler=self._run,
            is_mutating=False,
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        try:
            abs_path = safe_resolve_path(ctx.work_dir, args.get("path", "."), ctx.allowed_paths)
        except SandboxError as e:
            return ToolResult(ok=False, error=str(e))

        root = Path(abs_path)
        if not root.exists():
            return ToolResult(ok=False, error=f"Path not found: {args.get('path', '.')}")

        files = (
            [p for p in root.rglob("*.py") if p.is_file()]
            if root.is_dir()
            else ([root] if root.suffix == ".py" else [])
        )
        language = args.get("language", "python")
        pattern = args["pattern"]

        if language != "python":
            # Fall back: literal text search
            return await _fallback_text_search(ctx, root, files or [root], pattern)

        results: list[str] = []
        for file_path in files:
            try:
                source = file_path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(file_path))
            except (SyntaxError, OSError) as e:
                results.append(f"{file_path}: parse error: {e}")
                continue
            for node in ast.walk(tree):
                if _node_matches(node, pattern):
                    rel = file_path.relative_to(ctx.work_dir) if str(file_path).startswith(ctx.work_dir) else file_path.name
                    name = _node_name(node) or "<anonymous>"
                    results.append(f"{rel}:{getattr(node, 'lineno', '?')}: {name}")

        if not results:
            return ToolResult(ok=True, output="(no matches)")
        return ToolResult(ok=True, output=truncate_output("\n".join(results)))


_ALIASES: dict[str, str] = {
    "function_definition": "FunctionDef",
    "class_definition": "ClassDef",
    "import_statement": "Import",
    "import_from": "ImportFrom",
    "if_statement": "If",
    "for_statement": "For",
    "while_statement": "While",
    "try_statement": "Try",
    "with_statement": "With",
    "return_statement": "Return",
    "call": "Call",
    "assignment": "Assign",
}


def _node_matches(node: ast.AST, pattern: str) -> bool:
    """Match a node by snake_case alias (e.g. 'function_definition' -> ast.FunctionDef)."""
    cls_name = type(node).__name__
    aliased = _ALIASES.get(pattern)
    if aliased and cls_name == aliased:
        return True
    snake = _to_snake_case(cls_name)
    return snake == pattern or cls_name.lower() == pattern.lower()


def _to_snake_case(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _node_name(node: ast.AST) -> str | None:
    return getattr(node, "name", None)


async def _fallback_text_search(ctx, root, files, pattern) -> ToolResult:
    results: list[str] = []
    for file_path in files:
        if not file_path.is_file():
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines()):
            if pattern in line:
                rel = file_path.relative_to(ctx.work_dir) if str(file_path).startswith(ctx.work_dir) else file_path.name
                results.append(f"{rel}:{i + 1}: {line}")
    if not results:
        return ToolResult(ok=True, output="(no matches)")
    return ToolResult(ok=True, output=truncate_output("\n".join(results)))
