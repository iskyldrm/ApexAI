"""Cost API endpoints (Sub-System D Phase 7)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.cost.budget import list_recent_alerts, org_spend_summary
from app.cost.tiers import MODEL_TIERS, Tier
from app.db import async_session_maker


router = APIRouter(prefix="/api/v1/cost", tags=["cost"])


async def get_session(request: Request) -> AsyncSession:
    """Per-request session — opens and closes per call."""
    async with async_session_maker() as session:
        yield session


@router.get("/tiers")
async def list_tiers() -> dict:
    """Return the current model tier table."""
    return {
        "tiers": [
            {
                "tier": int(tier),
                "model": cfg.model,
                "provider": cfg.provider,
                "input_price_per_million": cfg.input_price_per_million,
                "output_price_per_million": cfg.output_price_per_million,
                "max_input_tokens": cfg.max_input_tokens,
                "notes": cfg.notes,
            }
            for tier, cfg in MODEL_TIERS.items()
        ],
    }


@router.get("/usage")
async def usage_summary(
    org_id: str = Query(..., description="Org UUID"),
    daily_cap: int = Query(10_000_000, description="Daily token cap"),
    days: int = Query(7, description="Lookback window in days"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Org spend summary for the past N days."""
    return await org_spend_summary(session, org_id=org_id, daily_cap=daily_cap, days=days)


@router.get("/alerts")
async def recent_alerts(
    org_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Recent budget alerts (optionally filtered by org)."""
    alerts = await list_recent_alerts(session, org_id=org_id, limit=limit)
    return [
        {
            "id": str(a.id),
            "org_id": a.org_id,
            "kind": a.kind,
            "threshold": a.threshold,
            "actual": a.actual,
            "period": a.period,
            "created_at": a.created_at.isoformat(),
        }
        for a in alerts
    ]