"""Test-runner REST API (Sub-System E)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_maker
from app.testing.flakiness import compute_flakiness
from app.testing.service import TestRunService


router = APIRouter(prefix="/api/v1/test-runs", tags=["test-runs"])


class RunTestsRequest(BaseModel):
    project_path: str
    language: str = "python"
    framework: str | None = None
    test_filter: str | None = None
    network: bool = False
    timeout_seconds: int = Field(default=600, ge=10, le=3600)
    env_overrides: dict[str, str] = Field(default_factory=dict)


async def get_session(request: Request) -> AsyncSession:
    async with async_session_maker() as session:
        yield session


@router.post("")
async def create_test_run(
    body: RunTestsRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Manually trigger a test run."""
    from app.testing.runner import RunSpec

    spec = RunSpec(
        language=body.language,
        project_path=body.project_path,
        framework=body.framework,
        test_filter=body.test_filter,
        network=body.network,
        timeout_seconds=body.timeout_seconds,
        env_overrides=body.env_overrides,
    )
    service = TestRunService()
    test_run = await service.run(session, spec)
    return {
        "id": str(test_run.id),
        "status": test_run.status,
        "total": test_run.total,
        "passed": test_run.passed,
        "failed": test_run.failed,
        "duration_ms": test_run.duration_ms,
    }


@router.get("")
async def list_test_runs(
    project_path: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    service = TestRunService()
    runs = await service.list_runs(
        session, project_path=project_path, status=status, limit=limit
    )
    return [
        {
            "id": str(r.id),
            "project_path": r.project_path,
            "language": r.language,
            "framework": r.framework,
            "status": r.status,
            "total": r.total,
            "passed": r.passed,
            "failed": r.failed,
            "duration_ms": r.duration_ms,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in runs
    ]


@router.get("/flakiness")
async def flakiness_report(
    project_path: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Per-test flakiness summary over the recent runs."""
    report = await compute_flakiness(session, project_path=project_path)
    return {
        "flaky_tests": report.flaky_tests,
        "broken_tests": report.broken_tests,
        "stable_tests": report.stable_tests,
    }