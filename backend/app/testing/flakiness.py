"""Flakiness detector — tracks per-test pass/fail history.

A test is "flaky" if it has both passed and failed in the recent N runs.
Used by:
- The CI dashboard to mark flaky tests
- Auto-retry logic to silently re-run flaky tests once
- The pipeline orchestrator to exclude flaky tests from "blocking" status

Algorithm:
- Look at the last ``LOOKBACK_RUNS`` runs
- For each test name, count pass/fail
- Pass rate > 0 AND < 1 → flaky
- Pass rate == 0 → consistently broken
- Pass rate == 1 → consistently green
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.testing import TestRun, TestRunRecord


LOOKBACK_RUNS = 10


@dataclass
class FlakinessReport:
    """Summary of one flakiness scan."""

    flaky_tests: list[dict]
    broken_tests: list[dict]
    stable_tests: int


async def compute_flakiness(
    session: AsyncSession,
    *,
    project_path: str | None = None,
    lookback: int = LOOKBACK_RUNS,
) -> FlakinessReport:
    """Scan recent TestRunRecords and classify tests as flaky / broken / stable."""
    # Pull the most recent N runs (optionally for one project)
    stmt = select(TestRun).order_by(TestRun.started_at.desc()).limit(lookback)
    if project_path:
        stmt = stmt.where(TestRun.project_path == project_path)
    runs = (await session.execute(stmt)).scalars().all()
    if not runs:
        return FlakinessReport(flaky_tests=[], broken_tests=[], stable_tests=0)

    run_ids = [r.id for r in runs]
    recs_stmt = select(TestRunRecord).where(TestRunRecord.test_run_id.in_(run_ids))
    records = (await session.execute(recs_stmt)).scalars().all()

    # Group by test_name
    by_test: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        by_test[rec.test_name].append(rec.status)

    flaky: list[dict] = []
    broken: list[dict] = []
    stable = 0

    for test_name, statuses in by_test.items():
        n = len(statuses)
        passed = sum(1 for s in statuses if s == "passed")
        rate = passed / n if n else 0
        if 0 < rate < 1:
            flaky.append({
                "test_name": test_name,
                "pass_rate": rate,
                "runs": n,
            })
        elif rate == 0:
            broken.append({
                "test_name": test_name,
                "pass_rate": 0,
                "runs": n,
            })
        else:
            stable += 1

    # Sort by lowest pass rate first
    flaky.sort(key=lambda t: t["pass_rate"])
    broken.sort(key=lambda t: t["pass_rate"])

    return FlakinessReport(
        flaky_tests=flaky,
        broken_tests=broken,
        stable_tests=stable,
    )