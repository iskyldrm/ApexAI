"""Agent REST API — converse, get run, cancel, list, admin, resume, export.

POST /agent/converse                  → run the agent loop synchronously
POST /agent/converse/stream           → SSE event stream
GET  /agent/runs/{id}                 → fetch run + recent messages
POST /agent/runs/{id}/cancel          → cancel a running run
POST /agent/runs/{id}/resume         → resume a paused run (with approval)
GET  /agent/runs/{id}/export          → full conversation export (Task 43)
GET  /agent/runs                      → list runs (filter by org/role/status)
POST /agent/admin/cleanup             → platform admin: mark stuck runs
GET  /agent/admin/stats               → platform admin: aggregated stats
GET  /agent/usage/summary             → org usage summary (Task 61)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.cleanup import mark_stuck_runs
from app.agent.llm.litellm_client import LiteLLMClient
from app.agent.memory import Message, export_conversation
from app.agent.model_resolver import resolve_default_model
from app.agent.observability import log_agent_event
from app.agent.observability.metrics import record_agent_run
from app.agent.roles import Role, get_role_config
from app.agent.runtime import AgentLoop, AgentLoopConfig, AgentResult
from app.agent.tool_parser import parse_tool_calls
from app.core.rbac import require_permission
from app.deps import get_current_user, get_db
from app.enums import Permission
from app.models.agent_run import AgentRun
from app.models.conversation import Conversation, ConversationMessage
from app.models.token_usage import TokenUsage
from app.schemas.agent import ConverseRequest, ConverseResponse, StreamEvent
from sqlalchemy import func, select


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


def _llm_for_org(db: AsyncSession, org_id: str | None) -> LiteLLMClient:
    """Build a LiteLLM client that records token usage to the token_usage table."""
    async def record(model: str, _model2: str, input_tokens: int, output_tokens: int, cost: float) -> None:
        if not org_id:
            return
        db.add(TokenUsage(
            org_id=org_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        ))
        await db.commit()
    return LiteLLMClient(token_callback=record)


@router.post("/converse", response_model=ConverseResponse)
async def converse(
    body: ConverseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ConverseResponse:
    """Run the agent loop synchronously and return the final result."""
    try:
        role = Role(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")

    role_cfg = get_role_config(role)
    llm = _llm_for_org(db, body.org_id and str(body.org_id))

    # Task 60: resolve model via settings table (user > org > platform > role default)
    model = await resolve_default_model(
        db,
        role=role,
        org_id=body.org_id and str(body.org_id),
        user_id=current_user.get("sub"),
        request_override=body.model_override,
    )

    # Resolve API key from org vault (F's keys.py logic is reused by AgentLoop
    # via the api_key kwarg — left None here means the LLM uses its own env var)
    config = AgentLoopConfig(
        role=role,
        user_prompt=body.prompt,
        work_dir=body.work_dir,
        user_id=current_user.get("sub"),
        org_id=body.org_id and str(body.org_id),
        max_steps=body.max_steps,
        model=model,
        resume_conversation_id=body.resume_conversation_id,
        resume_agent_run_id=body.resume_agent_run_id,
    )

    loop = AgentLoop(llm_client=llm, session=db)
    result = await loop.run(config)

    # Emit Prometheus metrics
    record_agent_run(
        role=role.value,
        model=result.cost_usd is not None and body.model_override or role_cfg.default_model,
        finish_reason=result.finish_reason,
        steps=result.steps,
        duration_seconds=result.duration_ms / 1000.0,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )

    # Log the run
    await log_agent_event(
        action=f"agent.{result.finish_reason}",
        agent_run_id=str(result.agent_run_id),
        role=role.value,
        actor_id=current_user.get("sub"),
        actor_email=current_user.get("email"),
        org_id=body.org_id and str(body.org_id),
        metadata={
            "steps": result.steps,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "duration_ms": result.duration_ms,
        },
    )

    return ConverseResponse(
        success=result.success,
        agent_run_id=result.agent_run_id,
        conversation_id=result.conversation_id,
        summary=result.summary,
        steps=result.steps,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        duration_ms=result.duration_ms,
        intentional_files=result.intentional_files,
        error=result.error,
        finish_reason=result.finish_reason,
    )


@router.post("/converse/stream")
async def converse_stream(
    body: ConverseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Stream agent steps as Server-Sent Events.

    The full run executes server-side; events are emitted as the loop
    progresses. (A future optimization: wire the loop's internal events
    into a queue so we can stream before the run completes.)
    """
    try:
        role = Role(body.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")

    async def event_gen() -> AsyncGenerator[str, None]:
        # Emit a start event
        yield _sse("agent.started", {"role": role.value})

        # For now, the stream variant just runs the sync loop and emits
        # a single finished event with the result. (See Phase 6 in plan
        # for the full incremental stream — requires event-queue hookup.)
        try:
            response = await converse(body, db=db, current_user=current_user)
            yield _sse(
                "agent.finished",
                response.model_dump(mode="json"),
            )
        except Exception as e:
            yield _sse("agent.error", {"error": str(e)})

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get("/runs/{run_id}")
async def get_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Fetch an agent run + its conversation messages."""
    run = await db.get(AgentRun, str(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")

    # RBAC: user must be the run's user, or an org admin/manager
    is_owner = str(run.user_id) == current_user.get("sub")
    if not is_owner and not current_user.get("is_platform_admin"):
        # In a fuller impl, check org membership here
        pass

    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == run.conversation_id)
        .order_by(ConversationMessage.sequence)
    )
    messages = [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "tool_calls": m.tool_calls,
            "tool_result": m.tool_result,
            "tool_name": m.tool_name,
            "tool_call_id": m.tool_call_id,
            "sequence": m.sequence,
            "input_tokens": m.input_tokens,
            "output_tokens": m.output_tokens,
        }
        for m in result.scalars()
    ]
    return {
        "id": str(run.id),
        "conversation_id": str(run.conversation_id),
        "role": run.role,
        "model": run.model,
        "status": run.status,
        "steps": run.steps,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "duration_ms": run.duration_ms,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "messages": messages,
    }


@router.get("/usage/summary")
async def usage_summary(
    org_id: UUID | None = None,
    period: str = Query("7d", pattern="^(1d|7d|30d)$"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Token usage + cost summary over a recent period (Task 61).

    Default 7 days. org_id required for non-platform-admin.
    """
    is_pa = current_user.get("is_platform_admin", False)
    if not is_pa and not org_id:
        raise HTTPException(status_code=400, detail="org_id required")

    days = {"1d": 1, "7d": 7, "30d": 30}[period]
    threshold = datetime.utcnow() - timedelta(days=days)

    q = select(
        func.count(TokenUsage.id).label("calls"),
        func.coalesce(func.sum(TokenUsage.input_tokens), 0).label("input"),
        func.coalesce(func.sum(TokenUsage.output_tokens), 0).label("output"),
        func.coalesce(func.sum(TokenUsage.cost_usd), 0.0).label("cost"),
    ).where(TokenUsage.created_at >= threshold)
    if org_id:
        q = q.where(TokenUsage.org_id == str(org_id))
    totals = (await db.execute(q)).one()

    by_model = select(
        TokenUsage.model,
        func.coalesce(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens), 0).label("tokens"),
    ).where(TokenUsage.created_at >= threshold)
    if org_id:
        by_model = by_model.where(TokenUsage.org_id == str(org_id))
    by_model = by_model.group_by(TokenUsage.model).order_by(func.sum(TokenUsage.input_tokens + TokenUsage.output_tokens).desc())
    model_rows = (await db.execute(by_model)).all()

    return {
        "period": period,
        "calls": totals.calls,
        "input_tokens": int(totals.input),
        "output_tokens": int(totals.output),
        "total_tokens": int(totals.input) + int(totals.output),
        "cost_usd": float(totals.cost),
        "by_model": [{"model": m, "tokens": int(t)} for m, t in model_rows],
    }


@router.get("/runs")
async def list_runs(
    org_id: UUID | None = None,
    role: str | None = None,
    status: str | None = None,
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """List agent runs (filter by org/role/status)."""
    query = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
    if org_id:
        query = query.where(AgentRun.org_id == str(org_id))
    if role:
        query = query.where(AgentRun.role == role)
    if status:
        query = query.where(AgentRun.status == status)
    result = await db.execute(query)
    return {
        "items": [
            {
                "id": str(r.id),
                "conversation_id": str(r.conversation_id),
                "role": r.role,
                "model": r.model,
                "status": r.status,
                "steps": r.steps,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "duration_ms": r.duration_ms,
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r in result.scalars()
        ]
    }


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Export the full conversation as JSON (Task 43)."""
    run = await db.get(AgentRun, str(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    result = await db.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == run.conversation_id)
        .order_by(ConversationMessage.sequence)
    )
    msgs = [
        Message(
            role=m.role,
            content=m.content,
            tool_calls=m.tool_calls,
            tool_call_id=m.tool_call_id,
            tool_name=m.tool_name,
            id=m.id,
            parent_id=m.parent_message_id,
            input_tokens=m.input_tokens,
            output_tokens=m.output_tokens,
        )
        for m in result.scalars()
    ]
    exported = export_conversation(msgs)
    exported["agent_run_id"] = str(run.id)
    exported["role"] = run.role
    exported["status"] = run.status
    return exported


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: UUID,
    body: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Resume a paused or awaiting_approval run.

    Body: { "approval_comment": "..." } for plan/migration approvals,
    or empty {} to simply continue.
    """
    run = await db.get(AgentRun, str(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status not in ("awaiting_approval", "paused", "stuck"):
        raise HTTPException(
            status_code=400,
            detail=f"Run is {run.status}, cannot resume",
        )

    # Append approval to conversation as a system message
    conv_id = run.conversation_id
    # Find the current max sequence
    seq_result = await db.execute(
        select(func.coalesce(func.max(ConversationMessage.sequence), 0)).where(
            ConversationMessage.conversation_id == conv_id
        )
    )
    next_seq = (seq_result.scalar() or 0) + 1
    msg = ConversationMessage(
        conversation_id=conv_id,
        role="system",
        content=f"[RESUMED by user] {(body or {}).get('approval_comment', '')}",
        sequence=next_seq,
    )
    db.add(msg)
    run.status = "running"
    run.error = None
    await db.commit()

    # Re-run with resume_conversation_id
    role = Role(run.role)
    config = AgentLoopConfig(
        role=role,
        user_prompt=run.role,  # original prompt not stored; re-execute same role
        work_dir="/tmp",
        user_id=current_user.get("sub"),
        org_id=run.org_id,
        resume_conversation_id=run.conversation_id,
        resume_agent_run_id=run.id,
    )

    # Re-execute the loop
    llm = _llm_for_org(db, run.org_id)
    loop = AgentLoop(llm_client=llm, session=db)
    result = await loop.run(config)

    return {
        "agent_run_id": str(result.agent_run_id),
        "success": result.success,
        "finish_reason": result.finish_reason,
        "summary": result.summary,
        "steps": result.steps,
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Cancel a running agent run. Marks it as 'cancelled'."""
    run = await db.get(AgentRun, str(run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status not in ("running",):
        raise HTTPException(
            status_code=400,
            detail=f"Run is {run.status}, cannot cancel",
        )
    run.status = "cancelled"
    run.error = "Cancelled by user"
    run.finished_at = datetime.utcnow()
    await db.commit()
    await log_agent_event(
        action="agent.cancelled",
        agent_run_id=str(run.id),
        role=run.role,
        actor_id=current_user.get("sub"),
        actor_email=current_user.get("email"),
        org_id=run.org_id,
    )
    return {"status": "cancelled", "agent_run_id": str(run.id)}


@router.post("/admin/cleanup")
async def admin_cleanup(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Platform-admin endpoint: mark all stuck runs (>1h running) as stuck."""
    if not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin required")
    count = await mark_stuck_runs(db)
    return {"marked_stuck": count}


@router.get("/admin/stats")
async def admin_stats(
    org_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Platform-admin endpoint: aggregated agent stats (counts, tokens, cost)."""
    if not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin required")

    base = select(
        func.count(AgentRun.id).label("total_runs"),
        func.coalesce(func.sum(AgentRun.input_tokens), 0).label("total_input"),
        func.coalesce(func.sum(AgentRun.output_tokens), 0).label("total_output"),
        func.coalesce(func.sum(AgentRun.cost_usd), 0.0).label("total_cost"),
    )
    if org_id:
        base = base.where(AgentRun.org_id == str(org_id))
    totals = (await db.execute(base)).one()

    by_status_q = select(
        AgentRun.status, func.count(AgentRun.id)
    ).group_by(AgentRun.status)
    if org_id:
        by_status_q = by_status_q.where(AgentRun.org_id == str(org_id))
    by_status = {s: c for s, c in (await db.execute(by_status_q)).all()}

    return {
        "total_runs": totals.total_runs,
        "total_input_tokens": int(totals.total_input),
        "total_output_tokens": int(totals.total_output),
        "total_cost_usd": float(totals.total_cost),
        "by_status": by_status,
    }
