"""Tests for budget alerts (Sub-System D Phase 6)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.cost.budget import (
    THRESHOLDS,
    check_and_record_daily_alert,
    list_recent_alerts,
    org_spend_summary,
)
from app.db import async_session_maker
from app.models.budget_alert import BudgetAlert
from app.models.token_usage import TokenUsage


@pytest.fixture
async def fresh_org_session():
    """Yield a session with a unique test org, user, and api_key, clean up after."""
    from sqlalchemy import delete

    from app.models.api_key import ApiKey
    from app.models.org import Org
    from app.models.user import User

    org_id = uuid4()
    user_id = uuid4()
    key_id = uuid4()

    async with async_session_maker() as session:
        # Create minimal org + user + api_key (FKs required by token_usage)
        session.add(Org(id=org_id, name=f"test-budget-{org_id.hex[:6]}", slug=f"test-budget-{org_id.hex[:6]}"))
        session.add(User(id=user_id, email=f"test-budget-{user_id.hex[:6]}@test.local", password_hash="x", full_name="Test Budget User"))
        await session.flush()
        session.add(ApiKey(
            id=key_id,
            org_id=org_id,
            user_id=None,  # xor check: only org_id set
            provider="openai",
            label="test-budget-key",
            vault_path="secret/data/test",
            created_by=str(user_id),
        ))
        await session.commit()

        yield session, str(org_id), user_id, key_id

        # Cleanup
        await session.execute(delete(BudgetAlert).where(BudgetAlert.org_id == str(org_id)))
        await session.execute(delete(TokenUsage).where(TokenUsage.org_id == str(org_id)))
        await session.execute(delete(ApiKey).where(ApiKey.id == key_id))
        await session.execute(delete(User).where(User.id == user_id))
        await session.execute(delete(Org).where(Org.id == org_id))
        await session.commit()


@pytest.mark.asyncio
async def test_no_alert_when_under_threshold(fresh_org_session):
    """0 tokens used → no alert."""
    session, org_id, user_id, key_id = fresh_org_session
    alert = await check_and_record_daily_alert(
        session, org_id=org_id, daily_cap=10_000
    )
    assert alert is None


@pytest.mark.asyncio
async def test_no_alert_when_zero_cap(fresh_org_session):
    """No cap configured → no alerts (unlimited)."""
    session, org_id, user_id, key_id = fresh_org_session
    alert = await check_and_record_daily_alert(
        session, org_id=org_id, daily_cap=0
    )
    assert alert is None


@pytest.mark.asyncio
async def test_alert_at_50_percent(fresh_org_session):
    """Insert tokens to push usage to 50% of cap."""
    session, org_id, user_id, key_id = fresh_org_session
    cap = 1000

    # Insert 500 tokens (50%)
    tu = TokenUsage(
        user_id=str(user_id),  # FK relaxed via no actual FK in some configs
        org_id=org_id,
        api_key_id=str(key_id),
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=300,
        output_tokens=200,
        cost_usd=Decimal("0.001"),
    )
    session.add(tu)
    await session.commit()

    alert = await check_and_record_daily_alert(
        session, org_id=org_id, daily_cap=cap
    )
    assert alert is not None
    assert alert.kind == "daily_50"
    assert alert.threshold == 0.50


@pytest.mark.asyncio
async def test_alert_at_90_percent(fresh_org_session):
    from decimal import Decimal

    session, org_id, user_id, key_id = fresh_org_session
    cap = 1000
    tu = TokenUsage(
        user_id=str(user_id),
        org_id=org_id,
        api_key_id=str(key_id),
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=500,
        output_tokens=450,
        cost_usd=Decimal("0.001"),
    )
    session.add(tu)
    await session.commit()

    alert = await check_and_record_daily_alert(
        session, org_id=org_id, daily_cap=cap
    )
    assert alert is not None
    assert alert.kind == "daily_90"


@pytest.mark.asyncio
async def test_alert_at_100_percent(fresh_org_session):
    from decimal import Decimal

    session, org_id, user_id, key_id = fresh_org_session
    cap = 1000
    tu = TokenUsage(
        user_id=str(user_id),
        org_id=org_id,
        api_key_id=str(key_id),
        provider="openai",
        model="gpt-4o",
        input_tokens=600,
        output_tokens=500,
        cost_usd=Decimal("0.005"),
    )
    session.add(tu)
    await session.commit()

    alert = await check_and_record_daily_alert(
        session, org_id=org_id, daily_cap=cap
    )
    assert alert is not None
    assert alert.kind == "daily_100"
    assert alert.actual >= 1.0


@pytest.mark.asyncio
async def test_alert_dedup_same_kind_same_day(fresh_org_session):
    """Calling twice for the same threshold doesn't double-alert."""
    from decimal import Decimal

    session, org_id, user_id, key_id = fresh_org_session
    cap = 1000
    tu = TokenUsage(
        user_id=str(user_id),
        org_id=org_id,
        api_key_id=str(key_id),
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=300,
        output_tokens=200,
        cost_usd=Decimal("0.001"),
    )
    session.add(tu)
    await session.commit()

    first = await check_and_record_daily_alert(session, org_id=org_id, daily_cap=cap)
    second = await check_and_record_daily_alert(session, org_id=org_id, daily_cap=cap)
    assert first is not None
    assert second is None  # dedup


@pytest.mark.asyncio
async def test_list_recent_alerts(fresh_org_session):
    from decimal import Decimal

    session, org_id, user_id, key_id = fresh_org_session
    cap = 1000
    tu = TokenUsage(
        user_id=str(user_id),
        org_id=org_id,
        api_key_id=str(key_id),
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=500,
        output_tokens=450,
        cost_usd=Decimal("0.001"),
    )
    session.add(tu)
    await session.commit()

    await check_and_record_daily_alert(session, org_id=org_id, daily_cap=cap)
    alerts = await list_recent_alerts(session, org_id=org_id)
    assert len(alerts) >= 1
    assert alerts[0].kind in ("daily_50", "daily_90", "daily_100")


@pytest.mark.asyncio
async def test_org_spend_summary_includes_alerts(fresh_org_session):
    from decimal import Decimal

    session, org_id, user_id, key_id = fresh_org_session
    cap = 1000
    tu = TokenUsage(
        user_id=str(user_id),
        org_id=org_id,
        api_key_id=str(key_id),
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=300,
        output_tokens=200,
        cost_usd=Decimal("0.005"),
    )
    session.add(tu)
    await session.commit()

    await check_and_record_daily_alert(session, org_id=org_id, daily_cap=cap)
    summary = await org_spend_summary(session, org_id=org_id, daily_cap=cap, days=7)

    assert "today_tokens" in summary
    assert "last_7d_tokens" in summary
    assert "daily_cap" in summary
    assert "pct_today" in summary
    assert "alerts" in summary
    assert summary["today_tokens"] == 500
    assert summary["daily_cap"] == 1000
    assert summary["pct_today"] == 0.5


@pytest.mark.asyncio
async def test_thresholds_are_50_90_100():
    """Guard against accidental threshold tweaks."""
    assert THRESHOLDS == (0.50, 0.90, 1.00)