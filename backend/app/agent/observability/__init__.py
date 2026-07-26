"""Activity log helper — writes to the audit_log table."""
from app.core.audit import audit


async def log_agent_event(
    *,
    action: str,
    agent_run_id: str,
    role: str,
    actor_id: str | None = None,
    actor_email: str | None = None,
    org_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Convenience wrapper: log a per-step event for an agent run."""
    await audit(
        action=action,
        actor_id=actor_id or agent_run_id,
        actor_type="agent",
        actor_email=actor_email,
        target_type="agent_run",
        target_id=agent_run_id,
        org_id=org_id,
        metadata={"role": role, **(metadata or {})},
    )
