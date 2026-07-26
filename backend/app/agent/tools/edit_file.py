"""edit_file tool — atomic search-replace engine.

Supports multiple edits per call. Each edit is tried with:
1. Exact match
2. Whitespace-normalized match (collapse runs of whitespace, strip trailing)
3. (optional) fuzzy match via difflib (added in Task 11 per plan)

Edits are atomic: any failure rolls back the whole call.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.agent.sandbox import SandboxError, safe_resolve_path
from app.agent.tools.base import Tool, ToolContext, ToolResult


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _find_substring(haystack: str, needle: str) -> int:
    """Return index of needle in haystack, or -1. Try exact then normalized."""
    idx = haystack.find(needle)
    if idx >= 0:
        return idx

    needle_norm = _normalize(needle)
    if not needle_norm:
        return -1

    # Sliding window: compare normalized windows
    needle_len = len(needle_norm)
    tokens = _WHITESPACE_RE.sub(" ", haystack)
    pos = 0
    while pos <= len(tokens) - needle_len:
        window = tokens[pos : pos + needle_len + 50]  # extra slack
        if _normalize(window).startswith(needle_norm):
            # Map back to original index
            orig_idx = _map_to_original(haystack, pos)
            return orig_idx
        pos += 1
    return -1


def _map_to_original(haystack: str, tokens_pos: int) -> int:
    """Map a position in the whitespace-collapsed string back to the original."""
    # Walk original, skipping whitespace
    skipped = 0
    for i, ch in enumerate(haystack):
        if ch.isspace():
            continue
        if skipped == tokens_pos:
            return i
        skipped += 1
    return len(haystack)


class EditFileTool(Tool):
    """Search-replace edits. Atomic: all-or-nothing."""

    def __init__(self) -> None:
        super().__init__(
            name="edit_file",
            description=(
                "Apply one or more search-replace edits to a file. Each edit specifies "
                "old_text and new_text. The edits are applied in order, and the call "
                "is atomic — if any edit fails (text not found), no changes are written. "
                "Whitespace differences are tolerated."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {"type": "string"},
                                "new_text": {"type": "string"},
                            },
                            "required": ["old_text", "new_text"],
                        },
                        "minItems": 1,
                    },
                },
                "required": ["path", "edits"],
            },
            handler=self._run,
            is_mutating=True,
            required_permissions=("files:write",),
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        try:
            abs_path = safe_resolve_path(ctx.work_dir, args["path"], ctx.allowed_paths)
        except SandboxError as e:
            return ToolResult(ok=False, error=str(e))

        target = Path(abs_path)
        if not target.exists():
            return ToolResult(ok=False, error=f"File not found: {args['path']}")

        original = target.read_text(encoding="utf-8")
        new_content = original

        for i, edit in enumerate(args["edits"]):
            old = edit["old_text"]
            new = edit["new_text"]
            idx = _find_substring(new_content, old)
            if idx < 0:
                return ToolResult(
                    ok=False,
                    error=f"Edit {i + 1}/{len(args['edits'])}: text not found: {old[:60]!r}",
                )
            new_content = new_content[:idx] + new + new_content[idx + len(old) :]

        # All edits applied — write atomically (write to temp, rename)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(new_content, encoding="utf-8")
        tmp.replace(target)

        return ToolResult(
            ok=True,
            output=f"Applied {len(args['edits'])} edit(s) to {args['path']}",
            metadata={"path": args["path"], "edit_count": len(args["edits"])},
        )
