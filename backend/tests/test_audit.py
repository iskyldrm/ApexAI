import pytest
from sqlalchemy import select

from app.core.audit import audit
from app.db import async_session_maker
from app.models.audit_log import AuditLog


@pytest.mark.asyncio
async def test_audit_writes_entry():
    await audit(
        action="test.event",
        actor_id="audit-test-actor",
        actor_type="user",
        actor_email="test@example.com",
        org_id=None,
        metadata={"foo": "bar"},
    )
    async with async_session_maker() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.action == "test.event")
        )
        entries = result.scalars().all()
    assert len(entries) >= 1
    entry = entries[-1]
    assert entry.actor_email_snapshot == "test@example.com"
    assert entry.meta == {"foo": "bar"}