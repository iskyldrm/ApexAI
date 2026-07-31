"""REST API for scheduled workflows + templates (B.5-B.12)."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_maker
from app.workflow.scheduler import (
    create_schedule,
    delete_schedule,
    list_schedules,
    set_schedule_enabled,
)
from app.workflow.templates import (
    clone_template,
    get_template,
    list_templates,
    seed_templates,
)


router = APIRouter(tags=["workflows"])


async def get_session():
    async with async_session_maker() as session:
        yield session


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class CloneTemplateRequest(BaseModel):
    org_id: str | None = None
    user_id: str | None = None
    name: str | None = None


@router.get("/workflow-templates")
async def api_list_templates(
    category: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    # Auto-seed on first hit so the default templates appear
    await seed_templates(session)
    rows = await list_templates(session, category=category)
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "category": t.category,
            "description": t.description,
            "definition": t.definition,
        }
        for t in rows
    ]


@router.post("/workflow-templates/{template_id}/clone")
async def api_clone_template(
    template_id: UUID,
    body: CloneTemplateRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        process = await clone_template(
            session,
            template_id,
            org_id=body.org_id,
            user_id=body.user_id,
            name=body.name,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "process_id": str(process.id),
        "name": process.name,
        "status": process.status,
    }


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


class CreateScheduleRequest(BaseModel):
    process_id: UUID
    cron_expr: str = Field(..., description="Standard 5-field cron (e.g. '0 9 * * 1')")
    enabled: bool = True
    org_id: str | None = None


class ToggleScheduleRequest(BaseModel):
    enabled: bool


@router.post("/scheduled-processes")
async def api_create_schedule(
    body: CreateScheduleRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sched = await create_schedule(
        session,
        process_id=body.process_id,
        cron_expr=body.cron_expr,
        enabled=body.enabled,
        org_id=body.org_id,
    )
    return {
        "id": str(sched.id),
        "process_id": str(sched.process_id),
        "cron_expr": sched.cron_expr,
        "enabled": sched.enabled,
    }


@router.get("/scheduled-processes")
async def api_list_schedules(
    org_id: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = await list_schedules(session, org_id=org_id)
    return [
        {
            "id": str(s.id),
            "process_id": str(s.process_id),
            "cron_expr": s.cron_expr,
            "enabled": s.enabled,
            "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]


@router.delete("/scheduled-processes/{schedule_id}")
async def api_delete_schedule(
    schedule_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    deleted = await delete_schedule(session, schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"deleted": True}


@router.patch("/scheduled-processes/{schedule_id}/enabled")
async def api_toggle_schedule(
    schedule_id: UUID,
    body: ToggleScheduleRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    sched = await set_schedule_enabled(session, schedule_id, body.enabled)
    if sched is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {
        "id": str(sched.id),
        "enabled": sched.enabled,
    }