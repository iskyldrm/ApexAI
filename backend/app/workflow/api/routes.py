"""Workflow REST API.

POST   /processes                      → create
GET    /processes                      → list
GET    /processes/{id}                 → detail + steps + events
POST   /processes/{id}/start           → enqueue (set status=queued, steps=queued)
POST   /processes/{id}/cancel          → soft cancel
POST   /processes/{id}/resume          → re-queue paused steps
GET    /processes/{id}/events          → paginated event log
GET    /process-dlq                    → list DLQ
POST   /process-dlq/{id}/replay        → retry from DLQ
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models.process import Process, ProcessDLQ, ProcessEvent, ProcessStep
from app.schemas.process import (
    CreateProcessRequest,
    ProcessEventResponse,
    ProcessResponse,
    ProcessStepResponse,
)
from app.workflow.dag import DAGValidationError, validate_dag
from app.workflow.definition import ProcessDefinition
from app.workflow.state import (
    InvalidTransition,
    transition_process,
    transition_step,
)


router = APIRouter(tags=["processes"])
processes_router = APIRouter(prefix="/processes", tags=["processes"])
dlq_router = APIRouter(prefix="/process-dlq", tags=["process-dlq"])


@processes_router.post("", response_model=ProcessResponse, status_code=201)
async def create_process(
    body: CreateProcessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ProcessResponse:
    """Create a process (status='draft'). Call /start to enqueue."""
    # Validate DAG via Pydantic
    try:
        pdef = ProcessDefinition(
            name=body.name,
            steps=[s.model_dump() for s in body.steps],
            edges=[e.model_dump(by_alias=True) for e in body.edges],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid process definition: {e}")

    # Validate DAG structure (no cycles, unique names, valid edge endpoints)
    try:
        validate_dag(pdef.model_dump())
    except DAGValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    process = Process(
        name=body.name,
        definition=pdef.model_dump(),
        status="draft",
        inputs=body.inputs,
        org_id=current_user.get("active_org_id"),
        user_id=current_user.get("sub"),
        meta={"work_dir": body.work_dir} if body.work_dir else {},
    )
    db.add(process)
    await db.commit()
    await db.refresh(process)

    # Pre-create step rows
    for step_def in pdef.steps:
        db.add(ProcessStep(
            process_id=process.id,
            step_name=step_def.name,
            role=step_def.role,
            status="pending",
            prompt_template=step_def.prompt,
            max_attempts=step_def.max_attempts or 5,
        ))
    await db.commit()

    db.add(ProcessEvent(
        process_id=process.id,
        event_type="process.created",
        payload={"name": process.name, "step_count": len(pdef.steps)},
        actor_id=current_user.get("sub"),
    ))
    await db.commit()

    return await _serialize_process(db, process)


@processes_router.get("", response_model=list[ProcessResponse])
async def list_processes(
    status: str | None = None,
    org_id: UUID | None = None,
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[ProcessResponse]:
    query = select(Process).order_by(Process.created_at.desc()).limit(limit)
    if status:
        query = query.where(Process.status == status)
    if org_id:
        query = query.where(Process.org_id == str(org_id))
    result = await db.execute(query)
    out: list[ProcessResponse] = []
    for p in result.scalars():
        out.append(await _serialize_process(db, p))
    return out


@processes_router.get("/{process_id}", response_model=ProcessResponse)
async def get_process(
    process_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ProcessResponse:
    process = await db.get(Process, str(process_id))
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    return await _serialize_process(db, process)


@processes_router.post("/{process_id}/start", response_model=ProcessResponse)
async def start_process(
    process_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ProcessResponse:
    """Move a draft process to queued; mark root steps as queued."""
    process = await db.get(Process, str(process_id))
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    if process.status != "draft":
        raise HTTPException(
            status_code=400, detail=f"Process is {process.status}, cannot start"
        )
    try:
        await transition_process(
            db, process, "queued",
            actor_id=current_user.get("sub"),
        )
    except InvalidTransition as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Mark root steps as queued
    pdef = ProcessDefinition.model_validate(process.definition)
    root_names = {s.name for s in pdef.root_steps()}
    result = await db.execute(
        select(ProcessStep).where(
            ProcessStep.process_id == process.id,
            ProcessStep.step_name.in_(root_names),
        )
    )
    for step in result.scalars():
        step.status = "queued"
        db.add(ProcessEvent(
            process_id=process.id,
            step_id=step.id,
            event_type="step.queued",
            payload={"step_name": step.step_name},
        ))
    await db.commit()
    await db.refresh(process)
    return await _serialize_process(db, process)


@processes_router.post("/{process_id}/cancel", response_model=ProcessResponse)
async def cancel_process(
    process_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ProcessResponse:
    process = await db.get(Process, str(process_id))
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    try:
        await transition_process(
            db, process, "cancelled",
            actor_id=current_user.get("sub"),
        )
    except InvalidTransition as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Cancel any pending/queued/running steps
    result = await db.execute(
        select(ProcessStep).where(
            ProcessStep.process_id == process.id,
            ProcessStep.status.in_(("pending", "queued", "running", "retrying")),
        )
    )
    for step in result.scalars():
        try:
            await transition_step(
                db, step, "cancelled", actor_id=current_user.get("sub"),
            )
        except InvalidTransition:
            pass  # already terminal
    await db.commit()
    await db.refresh(process)
    return await _serialize_process(db, process)


@processes_router.post("/{process_id}/resume", response_model=ProcessResponse)
async def resume_process(
    process_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ProcessResponse:
    """Resume a paused process: re-queue paused steps and move process back to running."""
    process = await db.get(Process, str(process_id))
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    if process.status not in ("paused", "stuck"):
        raise HTTPException(
            status_code=400, detail=f"Process is {process.status}, cannot resume"
        )
    try:
        await transition_process(
            db, process, "running",
            actor_id=current_user.get("sub"),
        )
    except InvalidTransition as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Re-queue paused steps
    result = await db.execute(
        select(ProcessStep).where(
            ProcessStep.process_id == process.id,
            ProcessStep.status == "paused",
        )
    )
    for step in result.scalars():
        step.status = "queued"
        step.next_retry_at = None
    await db.commit()
    await db.refresh(process)
    return await _serialize_process(db, process)


@processes_router.get("/{process_id}/events", response_model=list[ProcessEventResponse])
async def get_events(
    process_id: UUID,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[ProcessEventResponse]:
    process = await db.get(Process, str(process_id))
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")
    result = await db.execute(
        select(ProcessEvent)
        .where(ProcessEvent.process_id == process.id)
        .order_by(ProcessEvent.id.desc())
        .limit(limit)
    )
    return [
        ProcessEventResponse(
            id=ev.id,
            event_type=ev.event_type,
            payload=ev.payload,
            actor_id=ev.actor_id,
            step_id=ev.step_id,
            created_at=ev.created_at,
        )
        for ev in result.scalars()
    ]


# --- DLQ ---


@dlq_router.get("")
async def list_dlq(
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    result = await db.execute(
        select(ProcessDLQ)
        .where(ProcessDLQ.resolved_at.is_(None))
        .order_by(ProcessDLQ.failed_at.desc())
        .limit(limit)
    )
    return {
        "items": [
            {
                "id": str(d.id),
                "process_id": str(d.process_id) if d.process_id else None,
                "step_id": str(d.step_id) if d.step_id else None,
                "reason": d.reason,
                "retry_count": d.retry_count,
                "failed_at": d.failed_at.isoformat() if d.failed_at else None,
                "payload": d.payload,
            }
            for d in result.scalars()
        ]
    }


@dlq_router.post("/{dlq_id}/replay")
async def replay_dlq(
    dlq_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Mark a DLQ row as 'replayed' and re-queue the underlying step."""
    dlq = await db.get(ProcessDLQ, str(dlq_id))
    if not dlq:
        raise HTTPException(status_code=404, detail="DLQ row not found")
    if dlq.resolved_at is not None:
        raise HTTPException(status_code=400, detail="Already resolved")

    # Re-queue the step
    step = await db.get(ProcessStep, str(dlq.step_id)) if dlq.step_id else None
    if step and step.status in ("failed",):
        step.status = "pending"
        step.attempt = 0
        step.next_retry_at = None
        step.error = None

    dlq.resolved_at = datetime.utcnow()
    dlq.resolution = "replayed"
    await db.commit()
    return {"replayed": True, "step_id": str(step.id) if step else None}


# --- helpers ---


async def _serialize_process(db: AsyncSession, process: Process) -> ProcessResponse:
    steps_result = await db.execute(
        select(ProcessStep)
        .where(ProcessStep.process_id == process.id)
        .order_by(ProcessStep.created_at)
    )
    steps = steps_result.scalars().all()
    return ProcessResponse(
        id=process.id,
        name=process.name,
        status=process.status,
        current_step=process.current_step,
        definition=process.definition,
        inputs=process.inputs or {},
        outputs=process.outputs or {},
        error=process.error,
        created_at=process.created_at,
        started_at=process.started_at,
        finished_at=process.finished_at,
        steps=[
            ProcessStepResponse(
                id=s.id,
                step_name=s.step_name,
                role=s.role,
                status=s.status,
                attempt=s.attempt,
                max_attempts=s.max_attempts,
                inputs=s.inputs or {},
                outputs=s.outputs or {},
                next_retry_at=s.next_retry_at,
                started_at=s.started_at,
                finished_at=s.finished_at,
                error=s.error,
                agent_run_id=s.agent_run_id,
            )
            for s in steps
        ],
    )
