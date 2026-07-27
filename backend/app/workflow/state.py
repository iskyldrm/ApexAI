"""State machine for Process + ProcessStep (event-sourced).

Allowed transitions are validated before write. Every transition emits
a ProcessEvent row so we can replay the process history at any time.

Process states:
    draft → queued → running → (completed | failed | paused | cancelled | stuck)
    running → paused (when an approval gate trips)
    paused → running (when user resumes)
    any → cancelled (user cancel)

Step states:
    pending → queued → running → (completed | failed | retrying | skipped | cancelled)
    retrying → pending (after backoff)
    failed → (process-level decision: DLQ)

Emits events:
    process.created | process.started | process.completed | process.failed
    process.paused | process.resumed | process.cancelled
    step.queued | step.started | step.completed | step.failed
    step.retrying | step.skipped | step.dlq
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.process import Process, ProcessEvent, ProcessStep


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Allowed transitions (source set → allowed targets)
# ---------------------------------------------------------------------------

PROCESS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"queued", "cancelled"},
    "queued": {"running", "cancelled", "stuck"},
    "running": {"completed", "failed", "paused", "cancelled", "stuck"},
    "paused": {"running", "cancelled"},
    "completed": set(),  # terminal
    "failed": set(),     # terminal
    "cancelled": set(),  # terminal
    "stuck": {"running", "cancelled"},
}

STEP_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"queued", "running", "cancelled", "skipped"},
    "queued": {"running", "cancelled"},
    "running": {"completed", "failed", "retrying", "cancelled"},
    "retrying": {"pending", "cancelled", "failed"},
    "completed": set(),  # terminal
    "failed": set(),     # terminal — DLQ'd
    "skipped": set(),    # terminal
    "cancelled": set(),  # terminal
}


class InvalidTransition(ValueError):
    """Raised when a state transition is not allowed."""


def can_transition_process(current: str, target: str) -> bool:
    return target in PROCESS_TRANSITIONS.get(current, set())


def can_transition_step(current: str, target: str) -> bool:
    return target in STEP_TRANSITIONS.get(current, set())


# ---------------------------------------------------------------------------
# Apply transition + emit event (single helper used by the API and worker)
# ---------------------------------------------------------------------------


async def transition_process(
    session: AsyncSession,
    process: Process,
    new_status: str,
    *,
    actor_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ProcessEvent:
    """Change a process's status (validates transition) and emit a ProcessEvent."""
    if not can_transition_process(process.status, new_status):
        raise InvalidTransition(
            f"Process {process.id}: cannot move {process.status!r} → {new_status!r}"
        )
    old = process.status
    process.status = new_status
    if new_status == "running" and not process.started_at:
        from datetime import datetime
        process.started_at = datetime.utcnow()
    if new_status in ("completed", "failed", "cancelled", "stuck"):
        from datetime import datetime
        process.finished_at = datetime.utcnow()
    event = ProcessEvent(
        process_id=process.id,
        event_type=f"process.{new_status}",
        payload={"from": old, "to": new_status, **(payload or {})},
        actor_id=actor_id,
    )
    session.add(event)
    return event


async def transition_step(
    session: AsyncSession,
    step: ProcessStep,
    new_status: str,
    *,
    actor_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ProcessEvent:
    """Change a step's status (validates transition) and emit a ProcessEvent."""
    if not can_transition_step(step.status, new_status):
        raise InvalidTransition(
            f"Step {step.id} ({step.step_name}): cannot move {step.status!r} → {new_status!r}"
        )
    old = step.status
    step.status = new_status
    event = ProcessEvent(
        process_id=step.process_id,
        step_id=step.id,
        event_type=f"step.{new_status}",
        payload={"from": old, "to": new_status, "step_name": step.step_name, **(payload or {})},
        actor_id=actor_id,
    )
    session.add(event)
    return event


# ---------------------------------------------------------------------------
# Replay: rebuild process status from events
# ---------------------------------------------------------------------------


def derive_process_status_from_events(events: list[ProcessEvent]) -> str:
    """Given an ordered list of events for a process, return the latest status.

    Used by the replay endpoint to derive the process status from the
    event log (the ``processes.status`` row is a cache; events are
    source of truth).
    """
    latest = "draft"
    for ev in events:
        if ev.event_type.startswith("process."):
            latest = ev.event_type.split(".", 1)[1]
    return latest
