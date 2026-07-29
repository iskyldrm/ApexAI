"""Notification helper — created separately to avoid circular imports.

The TaskService imports this; the Task/Notification models don't.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Notification


async def create_notification(
    session: AsyncSession,
    *,
    user_id: str,
    org_id: str | None = None,
    kind: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    """Insert a notification for a user (in-app bell)."""
    n = Notification(
        user_id=user_id,
        org_id=org_id,
        kind=kind,
        title=title,
        body=body,
        link=link,
    )
    session.add(n)
    await session.flush()
    return n