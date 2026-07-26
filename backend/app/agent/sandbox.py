"""Shared sandbox helpers — path validation + command blocklist.

Every file-touching tool routes reads/writes through ``safe_resolve_path`` so
the agent can't escape the work_dir or its declared allowed_paths.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Commands that should never be run by an agent, no matter what.
# The list is intentionally conservative — narrow cases only.
_BLOCKLIST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?-[a-zA-Z]*r[a-zA-Z]*\b|\brm\s+-rf\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\bmkfs(\.|\s|$)"),
    re.compile(r"\bdd\s+if="),
    re.compile(r"\bcurl\b.*\|\s*(ba)?sh\b"),
    re.compile(r":\(\)\s*\{.*\};:"),  # fork bomb
    re.compile(r"\b>\s*/dev/sd[a-z]\b"),
    re.compile(r"\bshutdown\b|\breboot\b|\bpoweroff\b"),
)


class SandboxError(PermissionError):
    """Raised when a tool action would escape the sandbox."""


def safe_resolve_path(work_dir: str, requested: str, allowed_paths: tuple[str, ...] = ()) -> str:
    """Resolve ``requested`` against ``work_dir`` and confirm the result is inside.

    If ``allowed_paths`` is non-empty, the resolved path must also be under
    one of those directories. Raises ``SandboxError`` on escape attempts.
    Returns the absolute path.
    """
    work = Path(work_dir).resolve()
    target = (work / requested).resolve() if not os.path.isabs(requested) else Path(requested).resolve()

    # Containment under work_dir
    try:
        target.relative_to(work)
    except ValueError:
        if not allowed_paths:
            raise SandboxError(f"Path escapes work_dir: {requested}") from None
        # Check allowed_paths explicitly
        if not any(_is_relative_to(target, Path(p).resolve()) for p in allowed_paths):
            raise SandboxError(f"Path not in allowed_paths: {requested}") from None

    return str(target)


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def assert_command_safe(command: str) -> None:
    """Raise SandboxError if command matches the blocklist."""
    for pattern in _BLOCKLIST_PATTERNS:
        if pattern.search(command):
            raise SandboxError(f"Blocked command pattern: {pattern.pattern}")


def truncate_output(text: str, max_bytes: int = 50_000) -> str:
    """Cap text at max_bytes; append a notice if trimmed."""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="replace") + f"\n... [truncated, total {len(encoded)} bytes]"
