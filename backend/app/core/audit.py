from typing import Any

from sqlalchemy import insert

from app.db import async_session_maker
from app.models.audit_log import AuditLog


async def audit(
    action: str,
    actor_id: str | None = None,
    actor_type: str = "system",
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    org_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write an audit log entry. Fire-and-forget pattern."""
    async with async_session_maker() as session:
        await session.execute(
            insert(AuditLog).values(
                actor_type=actor_type,
                actor_id=actor_id,
                actor_email_snapshot=actor_email,
                action=action,
                target_type=target_type,
                target_id=target_id,
                org_id=org_id,
                ip_address=ip_address,
                user_agent=user_agent,
                meta=metadata or {},
            )
        )
        await session.commit()