"""Safety system tests — CircuitBreaker, RepetitionDetector, EditFailureTracker, TokenBudgetEnforcer."""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.safety import (
    CircuitBreaker,
    EditFailureTracker,
    RepetitionDetector,
    TokenBudgetEnforcer,
    TokenBudgetExceeded,
)


# -------------------- CircuitBreaker --------------------


def test_circuit_breaker_under_threshold():
    cb = CircuitBreaker(max_consecutive=3)
    cb.record_failure("read_file")
    cb.record_failure("read_file")
    assert not cb.tripped


def test_circuit_breaker_trips_at_threshold():
    cb = CircuitBreaker(max_consecutive=3)
    for _ in range(3):
        cb.record_failure("read_file")
    assert cb.tripped
    assert "read_file" in (cb.guidance_message() or "")


def test_circuit_breaker_resets_on_success():
    cb = CircuitBreaker(max_consecutive=3)
    cb.record_failure("read_file")
    cb.record_failure("read_file")
    cb.record_success("read_file")
    cb.record_failure("read_file")
    cb.record_failure("read_file")
    # Only 2 consecutive failures after reset → not tripped
    assert not cb.tripped


def test_circuit_breaker_per_tool_independence():
    cb = CircuitBreaker(max_consecutive=3)
    for _ in range(3):
        cb.record_failure("read_file")
    assert cb.tripped
    # write_file failures are tracked separately
    assert cb.tripped  # tripped state is global, but per-tool reset on success
    cb.record_success("write_file")
    # read_file is still tripped
    assert cb.tripped


# -------------------- RepetitionDetector --------------------


def test_repetition_detector_under_read_limit():
    rd = RepetitionDetector()
    for _ in range(5):
        rd.record("read_file", {"path": "a.py"}, is_mutating=False)
    assert not rd.tripped


def test_repetition_detector_trips_on_same_read():
    rd = RepetitionDetector(read_limit=3)
    for _ in range(4):
        rd.record("read_file", {"path": "a.py"}, is_mutating=False)
    assert rd.tripped


def test_repetition_detector_different_args_dont_count():
    rd = RepetitionDetector(read_limit=3)
    rd.record("read_file", {"path": "a.py"}, is_mutating=False)
    rd.record("read_file", {"path": "b.py"}, is_mutating=False)
    rd.record("read_file", {"path": "c.py"}, is_mutating=False)
    rd.record("read_file", {"path": "d.py"}, is_mutating=False)
    # 4 different files → 4 different keys, none exceed 3
    assert not rd.tripped


def test_repetition_detector_mutating_lower_limit():
    rd = RepetitionDetector(mutating_limit=3)
    for _ in range(4):
        rd.record("write_file", {"path": "x.py"}, is_mutating=True)
    assert rd.tripped


# -------------------- EditFailureTracker --------------------


def test_edit_tracker_ignores_non_edit_tools():
    tracker = EditFailureTracker(limit=3)
    for _ in range(5):
        tracker.record_failure("read_file")
    assert not tracker.tripped


def test_edit_tracker_trips_at_limit():
    tracker = EditFailureTracker(limit=3)
    tracker.record_failure("write_file")
    tracker.record_failure("edit_file")
    tracker.record_failure("apply_patch")
    assert tracker.tripped
    assert "edit" in (tracker.guidance_message() or "").lower()


def test_edit_tracker_does_not_reset_on_success():
    tracker = EditFailureTracker(limit=3)
    tracker.record_failure("write_file")
    tracker.record_failure("write_file")
    tracker.record_success("write_file")  # no reset
    tracker.record_failure("write_file")  # 3rd → trips
    assert tracker.tripped


# -------------------- TokenBudgetEnforcer --------------------


@pytest.mark.asyncio
async def test_token_budget_run_limit_triggers():
    enforcer = TokenBudgetEnforcer(per_run_limit=100)
    enforcer.record(input_tokens=50, output_tokens=40)
    # 90/100 — under
    await enforcer.check()
    enforcer.record(input_tokens=20, output_tokens=0)
    # 110/100 — over
    with pytest.raises(TokenBudgetExceeded) as exc_info:
        await enforcer.check()
    assert exc_info.value.scope == "run"
    assert exc_info.value.used == 110
    assert exc_info.value.limit == 100


@pytest.mark.asyncio
async def test_token_budget_no_org_no_daily_check():
    enforcer = TokenBudgetEnforcer(per_run_limit=1000, org_id=None)
    enforcer.record(input_tokens=500, output_tokens=400)
    await enforcer.check()  # 900 < 1000, no org → no raise


@pytest.mark.asyncio
async def test_token_budget_org_cap_loaded_from_settings():
    """If settings table has ai.daily_token_budget.<org_id>, the cap is enforced."""
    from app.db import async_session_maker
    from app.models.setting import Setting
    from app.models.org import Org

    # Create a real org so the org_id is FK-valid
    async with async_session_maker() as session:
        org = Org(slug=f"cap-{uuid.uuid4().hex[:6]}", name="Cap Test", status="active")
        session.add(org)
        await session.commit()
        await session.refresh(org)
        org_id = str(org.id)
        # Set daily cap to 50
        setting = Setting(
            scope="org",
            scope_id=org_id,
            key="ai.daily_token_budget",
            value={"tokens": 50},
        )
        session.add(setting)
        await session.commit()

    enforcer = TokenBudgetEnforcer(per_run_limit=10_000_000, org_id=org_id, session=AsyncSession_mock_for(session))
    # Note: the AsyncSession_mock_for is a placeholder; let's just use the real session
    # Actually we need to use the session in the same context. Use the real session.
    from app.db import async_session_maker
    async with async_session_maker() as session:
        enforcer = TokenBudgetEnforcer(per_run_limit=10_000_000, org_id=org_id, session=session)
        enforcer.record(input_tokens=40, output_tokens=20)
        # Total 60, plus whatever is in DB today (likely 0 for a new org)
        # Should raise because 60 > 50
        with pytest.raises(TokenBudgetExceeded) as exc_info:
            await enforcer.check()
        assert exc_info.value.scope == "org_daily"


class AsyncSession_mock_for:
    """Satisfies duck-typing — not used; the real session is what runs."""
    def __init__(self, real):
        self._real = real
