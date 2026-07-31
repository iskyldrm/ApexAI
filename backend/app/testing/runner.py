"""Container + host runners for the test pipeline.

``ContainerRunner`` spawns a Docker container with the project's source
mounted read-only. ``HostRunner`` is a fallback for environments without
Docker — it runs the same command on the host but loses the isolation
guarantees.

Both return a uniform ``RunResult`` that adapters parse to ``TestRun``
DB rows.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.testing.adapters.python import PythonAdapter
from app.testing.adapters.node import NodeAdapter


logger = logging.getLogger(__name__)


# Image registry — pre-baked per-language test images.
# In dev, falls back to public images; in prod, set APEXAI_TEST_IMAGE_REGISTRY.
IMAGE_REGISTRY = {
    "python": os.environ.get("APEXAI_TEST_IMAGE_PYTHON", "python:3.12-slim"),
    "node": os.environ.get("APEXAI_TEST_IMAGE_NODE", "node:22-slim"),
    "go": os.environ.get("APEXAI_TEST_IMAGE_GO", "golang:1.22-alpine"),
    "rust": os.environ.get("APEXAI_TEST_IMAGE_RUST", "rust:1.75-slim"),
}


@dataclass
class RunSpec:
    """Specification for one test run."""

    language: str                   # "python" | "node" | "go" | "rust"
    project_path: str
    framework: str | None = None    # auto-detected if None
    test_filter: str | None = None  # pytest -k / vitest -t
    network: bool = False
    timeout_seconds: int = 600
    env_overrides: dict[str, str] = field(default_factory=dict)
    parallel: int = 1               # shards; 1 = no sharding
    extra_args: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    """Output of one test run (parsed)."""

    status: str                  # "passed" | "failed" | "errored" | "timeout"
    framework: str
    language: str
    image: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: int = 0
    raw_stdout: str = ""
    raw_stderr: str = ""
    exit_code: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


_ADAPTERS = {
    "python": PythonAdapter,
    "node": NodeAdapter,
}


def _adapter_for(spec: RunSpec):
    if spec.framework:
        # Explicit framework
        if spec.language == "python" and spec.framework in ("pytest", "unittest"):
            return PythonAdapter(spec)
        if spec.language == "node" and spec.framework in ("vitest", "jest", "mocha"):
            return NodeAdapter(spec)
    # Default to language adapter
    cls = _ADAPTERS.get(spec.language)
    if cls is None:
        raise ValueError(f"No adapter for language={spec.language!r}")
    return cls(spec)


# ---------------------------------------------------------------------------
# Container runner
# ---------------------------------------------------------------------------


class ContainerRunner:
    """Spawns a Docker container per test run."""

    def __init__(self) -> None:
        self._docker_available: bool | None = None

    def is_available(self) -> bool:
        """Detect Docker on PATH."""
        if self._docker_available is None:
            self._docker_available = shutil.which("docker") is not None
        return self._docker_available

    async def run(self, spec: RunSpec) -> RunResult:
        if not self.is_available():
            raise RuntimeError(
                "Docker not on PATH — use HostRunner or install docker"
            )

        adapter = _adapter_for(spec)
        image = IMAGE_REGISTRY.get(spec.language, "alpine:latest")
        cmd = adapter.build_command()
        workdir = Path(spec.project_path).resolve()

        # Build docker run command
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-i",  # keep stdin open so we can interrupt
            "-v", f"{workdir}:/workspace:ro",  # read-only source
            "-v", f"{workdir}/.cache:/workspace/.cache",  # writable cache
            "-w", "/workspace",
            "--cpus", "2.0",
            "--memory", "4g",
            "--pids-limit", "512",
        ]
        if not spec.network:
            docker_cmd += ["--network", "none"]
        for k, v in spec.env_overrides.items():
            docker_cmd += ["-e", f"{k}={v}"]
        docker_cmd += [image] + cmd

        start = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=spec.timeout_seconds
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                return RunResult(
                    status="timeout",
                    framework=adapter.framework_name,
                    language=spec.language,
                    image=image,
                    duration_ms=elapsed_ms,
                    exit_code=None,
                )
            exit_code = proc.returncode
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            logger.exception("ContainerRunner failed")
            return RunResult(
                status="errored",
                framework=adapter.framework_name,
                language=spec.language,
                image=image,
                duration_ms=int((time.perf_counter() - start) * 1000),
                exit_code=None,
                raw_stderr=str(e),
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result = adapter.parse_output(stdout, stderr, exit_code or 0)
        result.image = image
        result.duration_ms = elapsed_ms
        result.raw_stdout = stdout[:50_000]  # cap
        result.raw_stderr = stderr[:50_000]
        return result


# ---------------------------------------------------------------------------
# Host runner (fallback)
# ---------------------------------------------------------------------------


class HostRunner:
    """Run tests on the host — no isolation, no Docker dependency.

    Used for: dev laptops without Docker, CI without a Docker-in-Docker
    daemon, and unit tests. Output parsing + persistence work the same
    as the container runner.
    """

    async def run(self, spec: RunSpec) -> RunResult:
        adapter = _adapter_for(spec)
        cmd = adapter.build_command()
        env = {**os.environ, **spec.env_overrides}

        start = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=spec.project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=spec.timeout_seconds
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                return RunResult(
                    status="timeout",
                    framework=adapter.framework_name,
                    language=spec.language,
                    image="<host>",
                    duration_ms=elapsed_ms,
                )
            exit_code = proc.returncode
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
        except FileNotFoundError as e:
            return RunResult(
                status="errored",
                framework=adapter.framework_name,
                language=spec.language,
                image="<host>",
                duration_ms=int((time.perf_counter() - start) * 1000),
                raw_stderr=f"Command not found: {e}",
            )
        except Exception as e:
            return RunResult(
                status="errored",
                framework=adapter.framework_name,
                language=spec.language,
                image="<host>",
                duration_ms=int((time.perf_counter() - start) * 1000),
                raw_stderr=str(e),
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        result = adapter.parse_output(stdout, stderr, exit_code)
        result.image = "<host>"
        result.duration_ms = elapsed_ms
        result.raw_stdout = stdout[:50_000]
        result.raw_stderr = stderr[:50_000]
        return result


# ---------------------------------------------------------------------------
# Default runner
# ---------------------------------------------------------------------------


def get_default_runner():
    """Return a container runner if Docker is available, else host runner."""
    cr = ContainerRunner()
    if cr.is_available():
        return cr
    logger.warning("Docker not found — falling back to HostRunner")
    return HostRunner()