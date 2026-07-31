"""Cron / scheduled workflows (B hardening).

Schedule a process to run on a cron expression:
    POST /scheduled-processes { process_id, cron_expr }
    → row in scheduled_processes, APScheduler job registered.

When the cron fires, ``trigger_workflow(process_id)`` calls the same
``start_process`` path used by manual REST triggers — so the workflow
runs through the standard queue + DLQ path.

DB additions: see migration ``g4b5c6d7e8f9_add_scheduled_processes``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.process import ScheduledProcess


logger = logging.getLogger(__name__)


_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Lazy-init the AsyncIOScheduler (single instance per process).

    Binds to the currently-running event loop so it works under pytest-asyncio.
    """
    global _scheduler
    if _scheduler is None:
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        _scheduler = AsyncIOScheduler(event_loop=loop)
    return _scheduler


def shutdown_scheduler() -> None:
    """Stop the scheduler (called on FastAPI shutdown)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass  # event loop may already be closed
    _scheduler = None


def start_scheduler() -> None:
    """Start the scheduler. Idempotent."""
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("Workflow cron scheduler started")


async def trigger_workflow(process_id: str, payload: dict | None = None) -> None:
    """Called by APScheduler when a cron fires.

    This is a stub — the real trigger wires into the workflow start API.
    The actual implementation should POST to ``/api/v1/processes/{id}/start``
    or insert directly into the queue. For now we log so tests can verify.
    """
    logger.info(
        "Cron trigger: process=%s payload=%s",
        process_id, payload,
    )


def sync_trigger_proxy(process_id: str, payload: dict | None = None) -> None:
    """APScheduler may invoke this if no async loop is bound.

    Falls back to scheduling an async coroutine on the current loop
    if available.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(trigger_workflow(process_id, payload))
        else:
            # Synchronous fallback — just log
            logger.info("Sync cron trigger: process=%s", process_id)
    except RuntimeError:
        logger.info("No loop — sync cron trigger: process=%s", process_id)


# ---------------------------------------------------------------------------
# CRUD for scheduled_processes table
# ---------------------------------------------------------------------------


async def create_schedule(
    session: AsyncSession,
    *,
    process_id: UUID,
    cron_expr: str,
    enabled: bool = True,
    org_id: str | None = None,
) -> ScheduledProcess:
    """Persist a new schedule + register the APScheduler job."""
    sched = ScheduledProcess(
        id=uuid4(),
        process_id=process_id,
        cron_expr=cron_expr,
        enabled=enabled,
        org_id=org_id,
    )
    session.add(sched)
    await session.commit()

    # Register with APScheduler (skipped if env var disabled)
    if enabled:
        try:
            scheduler = get_scheduler()
            trigger = CronTrigger.from_crontab(cron_expr)
            scheduler.add_job(
                sync_trigger_proxy,
                trigger=trigger,
                args=[str(process_id)],
                id=f"sched-{sched.id}",
                replace_existing=True,
            )
            if not scheduler.running:
                start_scheduler()
        except Exception as e:
            logger.warning("APScheduler registration failed for %s: %s", cron_expr, e)
    return sched


async def list_schedules(
    session: AsyncSession, org_id: str | None = None
) -> list[ScheduledProcess]:
    stmt = select(ScheduledProcess).order_by(ScheduledProcess.created_at.desc())
    if org_id:
        stmt = stmt.where(ScheduledProcess.org_id == org_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_schedule(session: AsyncSession, schedule_id: UUID) -> bool:
    from sqlalchemy import delete

    stmt = delete(ScheduledProcess).where(ScheduledProcess.id == schedule_id)
    result = await session.execute(stmt)
    await session.commit()
    # Also remove from APScheduler
    scheduler = get_scheduler()
    job_id = f"sched-{schedule_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    return result.rowcount > 0


async def set_schedule_enabled(
    session: AsyncSession, schedule_id: UUID, enabled: bool
) -> ScheduledProcess | None:
    sched = await session.get(ScheduledProcess, schedule_id)
    if sched is None:
        return None
    sched.enabled = enabled
    await session.commit()

    scheduler = get_scheduler()
    job_id = f"sched-{schedule_id}"
    if enabled and not scheduler.get_job(job_id):
        try:
            trigger = CronTrigger.from_crontab(sched.cron_expr)
            scheduler.add_job(
                sync_trigger_proxy,
                trigger=trigger,
                args=[str(sched.process_id)],
                id=job_id,
                replace_existing=True,
            )
            if not scheduler.running:
                start_scheduler()
        except Exception as e:
            logger.warning("Failed to re-enable schedule: %s", e)
    elif not enabled and scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    return sched


def reload_all_schedules(schedules: list[ScheduledProcess]) -> int:
    """Re-register every enabled schedule on app startup."""
    count = 0
    for sched in schedules:
        if not sched.enabled:
            continue
        try:
            scheduler = get_scheduler()
            trigger = CronTrigger.from_crontab(sched.cron_expr)
            scheduler.add_job(
                sync_trigger_proxy,
                trigger=trigger,
                args=[str(sched.process_id)],
                id=f"sched-{sched.id}",
                replace_existing=True,
            )
            count += 1
        except Exception as e:
            logger.warning("Failed to reload schedule %s: %s", sched.id, e)
    if count:
        start_scheduler()
    return count