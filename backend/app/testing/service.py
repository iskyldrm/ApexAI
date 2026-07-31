"""TestRunService — orchestrates the test runner and persists results."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.testing import TestRun, TestRunRecord
from app.testing.runner import RunResult, RunSpec, get_default_runner


logger = logging.getLogger(__name__)


class TestRunService:
    """High-level service: run tests + persist results."""

    def __init__(self, runner=None) -> None:
        self.runner = runner or get_default_runner()

    async def run(
        self,
        session: AsyncSession,
        spec: RunSpec,
        *,
        agent_run_id: str | None = None,
    ) -> TestRun:
        """Run the test suite per ``spec`` and persist a TestRun row."""
        # Create the row up front so we have an ID for streaming logs
        test_run = TestRun(
            agent_run_id=agent_run_id,
            project_path=spec.project_path,
            language=spec.language,
            framework=spec.framework or "",
            status="running",
            network=spec.network,
        )
        session.add(test_run)
        await session.commit()

        # Run the actual test
        result = await self.runner.run(spec)

        # Update the row with the outcome
        test_run.status = result.status
        test_run.total = result.total
        test_run.passed = result.passed
        test_run.failed = result.failed
        test_run.skipped = result.skipped
        test_run.errors = result.errors
        test_run.duration_ms = result.duration_ms
        test_run.image = result.image
        test_run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
        test_run.meta = {
            "exit_code": result.exit_code,
            "stderr_excerpt": (result.raw_stderr or "")[:1000],
            "stdout_excerpt": (result.raw_stdout or "")[:1000],
        }
        await session.commit()
        logger.info(
            "TestRun %s finished: status=%s total=%d passed=%d failed=%d errors=%d in %dms",
            test_run.id, test_run.status, test_run.total, test_run.passed,
            test_run.failed, test_run.errors, test_run.duration_ms or 0,
        )
        return test_run

    async def list_runs(
        self,
        session: AsyncSession,
        *,
        project_path: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[TestRun]:
        from sqlalchemy import select

        stmt = select(TestRun).order_by(TestRun.started_at.desc()).limit(limit)
        if project_path:
            stmt = stmt.where(TestRun.project_path == project_path)
        if status:
            stmt = stmt.where(TestRun.status == status)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_run(self, session: AsyncSession, run_id: str) -> TestRun | None:
        from uuid import UUID

        return await session.get(TestRun, UUID(run_id))

    async def add_test_records(
        self,
        session: AsyncSession,
        test_run_id: str,
        records: list[dict[str, Any]],
    ) -> list[TestRunRecord]:
        """Persist per-test records for flakiness detection."""
        from uuid import UUID

        rows = [
            TestRunRecord(
                test_run_id=UUID(test_run_id),
                test_name=r["test_name"],
                status=r["status"],
                duration_ms=r.get("duration_ms", 0),
            )
            for r in records
        ]
        for row in rows:
            session.add(row)
        await session.commit()
        return rows