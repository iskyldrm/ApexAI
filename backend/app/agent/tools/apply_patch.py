"""apply_patch tool — atomic multi-file search-replace.

Unlike edit_file (single file), this tool applies edits to multiple files in
a single transaction. If any edit fails, all changes are rolled back.

Use cases: cross-file refactors (rename function, update import across N files).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.agent.sandbox import SandboxError, safe_resolve_path
from app.agent.tools.base import Tool, ToolContext, ToolResult


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _find_substring(haystack: str, needle: str) -> int:
    idx = haystack.find(needle)
    if idx >= 0:
        return idx
    needle_norm = _normalize(needle)
    if not needle_norm:
        return -1
    tokens = _WHITESPACE_RE.sub(" ", haystack)
    needle_len = len(needle_norm)
    pos = 0
    while pos <= len(tokens) - needle_len:
        window = tokens[pos : pos + needle_len + 50]
        if _normalize(window).startswith(needle_norm):
            return _map_to_original(haystack, pos)
        pos += 1
    return -1


def _map_to_original(haystack: str, tokens_pos: int) -> int:
    skipped = 0
    for i, ch in enumerate(haystack):
        if ch.isspace():
            continue
        if skipped == tokens_pos:
            return i
        skipped += 1
    return len(haystack)


class ApplyPatchTool(Tool):
    """Apply search-replace edits to multiple files atomically."""

    def __init__(self) -> None:
        super().__init__(
            name="apply_patch",
            description=(
                "Apply a list of search-replace edits to one or more files in a "
                "single atomic transaction. If ANY edit fails, NO changes are "
                "written. Use for cross-file refactors. Pass an empty old_text "
                "to create a new file."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "patches": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "old_text": {"type": "string"},
                                "new_text": {"type": "string"},
                            },
                            "required": ["path", "old_text", "new_text"],
                        },
                    },
                },
                "required": ["patches"],
            },
            handler=self._run,
            is_mutating=True,
            required_permissions=("files:write",),
        )

    async def _run(self, ctx: ToolContext, args: dict) -> ToolResult:
        patches = args.get("patches")
        if not patches:
            return ToolResult(ok=False, error="patches list is required and non-empty")

        # Phase 1: validate everything, capture original contents
        ops: list[dict] = []
        for i, patch in enumerate(patches):
            try:
                abs_path = safe_resolve_path(ctx.work_dir, patch["path"], ctx.allowed_paths)
            except SandboxError as e:
                return ToolResult(ok=False, error=f"patch {i + 1} ({patch['path']}): {e}")

            target = Path(abs_path)
            new_content: str | None = None

            if patch["old_text"] == "":
                # Create new file
                if target.exists():
                    return ToolResult(ok=False, error=f"patch {i + 1}: file already exists: {patch['path']}")
                new_content = patch["new_text"]
                original = None
            else:
                if not target.exists():
                    return ToolResult(ok=False, error=f"patch {i + 1}: file not found: {patch['path']}")
                original = target.read_text(encoding="utf-8")
                idx = _find_substring(original, patch["old_text"])
                if idx < 0:
                    return ToolResult(
                        ok=False,
                        error=f"patch {i + 1} ({patch['path']}): text not found: {patch['old_text'][:60]!r}",
                    )
                new_content = original[:idx] + patch["new_text"] + original[idx + len(patch["old_text"]) :]

            ops.append({"path": target, "original": original, "new_content": new_content, "rel": patch["path"]})

        # Phase 2: write atomically — write all files to .tmp then rename in one pass
        # If any rename fails, attempt to roll back previous renames.
        try:
            written: list[Path] = []
            for op in ops:
                tmp = op["path"].with_suffix(op["path"].suffix + ".tmp")
                tmp.write_text(op["new_content"], encoding="utf-8")
                os.replace(tmp, op["path"])
                written.append(op["path"])
        except Exception as e:
            # Best-effort rollback: restore originals for files we already touched
            for path, op in zip(written, ops[: len(written)]):
                try:
                    if op["original"] is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_text(op["original"], encoding="utf-8")
                except OSError:
                    pass
            return ToolResult(ok=False, error=f"Atomic write failed: {e}")

        return ToolResult(
            ok=True,
            output=f"Applied {len(ops)} patch(es) across {len({o['rel'] for o in ops})} file(s)",
            metadata={"patch_count": len(ops), "files": sorted({o["rel"] for o in ops})},
        )
