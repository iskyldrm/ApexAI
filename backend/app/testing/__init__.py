"""Sub-System E — Build/Test Pipeline.

Wraps project test execution in fresh, sandboxed Docker containers:
- Per-language base images (Python, Node, Go, Rust)
- Read-only source mount + writable cache
- Optional network access
- Structured JUnit XML / JSON output parsed server-side
- Result storage in `test_runs` table

When Docker is unavailable (CI without daemon, dev laptop), falls back
to a host-mode runner that invokes the framework directly (with the
same output parsing + persistence). Production deployments should
always have Docker; the fallback is for tests + minimal setups.
"""
from app.testing.runner import (
    ContainerRunner,
    HostRunner,
    RunSpec,
    RunResult,
    get_default_runner,
)


__all__ = [
    "ContainerRunner",
    "HostRunner",
    "RunSpec",
    "RunResult",
    "get_default_runner",
]