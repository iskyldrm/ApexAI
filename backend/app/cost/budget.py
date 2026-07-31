"""Budget alert thresholds for Sub-System D.

Wraps the existing ``TokenBudgetEnforcer`` with notification triggers:
- 50% of daily cap → "approaching limit" notification
- 90% of daily cap → "near limit" notification
- 100% of daily cap → "limit reached" notification
- per-run exceeded → "run aborted" notification

Notifications go through Sub-System C's notification system (in-app +
future email).

De-duplicates: each alert kind fires once per period per org (so we don't
spam every time the LLM makes another call after we've crossed 90%).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget_alert import BudgetAlert
from app.models.token_usage import TokenUsage as TU
from sqlalchemy import func


logger = logging.getLogger(__name__)


# Alert thresholds (percent of daily cap)
THRESHOLDS: tuple[float, ...] = (0.50, 0.90, 1.00)

# Map threshold to alert kind
_THRESHOLD_KIND = {
    0.50: "daily_50",
    0.90: "daily_90",
    1.00: "daily_100",
}


async def check_and_record_daily_alert(
    session: AsyncSession,
    *,
    org_id: str,
    daily_cap: int,
    user_id: str | None = None,
) -> BudgetAlert | None:
    """If today's usage crossed a new threshold, persist a BudgetAlert row.

    Returns the new alert, or None if no new threshold was crossed today.
    """
    if not org_id or daily_cap <= 0:
        return None

    # Sum today's tokens
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    stmt = select(
        func.coalesce(func.sum(TU.input_tokens + TU.output_tokens), 0)
    ).where(
        TU.org_id == org_id,
        TU.created_at >= today_start,
    )
    result = await session.execute(stmt)
    used_today = int(result.scalar() or 0)
    pct = used_today / daily_cap

    # Find the highest threshold crossed
    crossed: float | None = None
    for t in sorted(THRESHOLDS):
        if pct >= t:
            crossed = t

    if crossed is None:
        return None

    # De-dupe: only one alert per kind per day per org
    period = today_start.strftime("%Y-%m-%d")
    existing = await session.execute(
        select(BudgetAlert).where(
            BudgetAlert.org_id == org_id,
            BudgetAlert.kind == _THRESHOLD_KIND[crossed],
            BudgetAlert.period == period,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    alert = BudgetAlert(
        id=uuid4(),
        org_id=org_id,
        kind=_THRESHOLD_KIND[crossed],
        threshold=crossed,
        actual=pct,
        period=period,
        metadata={"tokens_used": used_today, "cap": daily_cap, "user_id": user_id},
    )
    session.add(alert)
    await session.commit()
    logger.warning(
        "Budget alert [%s]: org=%s pct=%.0f%% (%d/%d tokens)",
        alert.kind, org_id, pct * 100, used_today, daily_cap,
    )
    return alert


async def list_recent_alerts(
    session: AsyncSession,
    *,
    org_id: str | None = None,
    limit: int = 50,
) -> list[BudgetAlert]:
    """List recent budget alerts, optionally filtered by org."""
    stmt = select(BudgetAlert).order_by(BudgetAlert.created_at.desc()).limit(limit)
    if org_id is not None:
        stmt = stmt.where(BudgetAlert.org_id == org_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def org_spend_summary(
    session: AsyncSession,
    *,
    org_id: str,
    daily_cap: int,
    days: int = 7,
) -> dict[str, Any]:
    """Compute spend summary for the past ``days`` days.

    Returns: {today, yesterday, last_7d, daily_cap, pct_today, alerts[]}
    """
    from datetime import timedelta

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=days)

    # Today
    today_stmt = select(
        func.coalesce(func.sum(TU.input_tokens + TU.output_tokens), 0),
        func.coalesce(func.sum(TU.cost_usd), 0.0),
    ).where(TU.org_id == org_id, TU.created_at >= today_start)

    today = (await session.execute(today_stmt)).one()

    # Last N days
    week_stmt = select(
        func.coalesce(func.sum(TU.input_tokens + TU.output_tokens), 0),
        func.coalesce(func.sum(TU.cost_usd), 0.0),
    ).where(TU.org_id == org_id, TU.created_at >= week_start)

    week = (await session.execute(week_stmt)).one()

    pct_today = (today[0] / daily_cap) if daily_cap > 0 else 0.0
    alerts = await list_recent_alerts(session, org_id=org_id, limit=10)

    return {
        "today_tokens": int(today[0]),
        "today_cost_usd": float(today[1]),
        "last_7d_tokens": int(week[0]),
        "last_7d_cost_usd": float(week[1]),
        "daily_cap": daily_cap,
        "pct_today": float(pct_today),
        "alerts": [
            {
                "kind": a.kind,
                "threshold": a.threshold,
                "actual": a.actual,
                "period": a.period,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ],
    }