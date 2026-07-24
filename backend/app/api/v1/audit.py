"""Audit log read endpoint."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import require_org_role
from app.deps import get_current_user, get_db
from app.enums import Role
from app.models.audit_log import AuditLog
from app.models.membership import OrgMembership

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("")
async def list_audit_log(
    org_id: UUID | None = None,
    action: str | None = None,
    actor_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    skip: int = Query(0, ge=0),
    take: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    is_platform_admin = current_user.get("is_platform_admin", False)
    if not is_platform_admin:
        if not org_id:
            raise HTTPException(
                status_code=400, detail="org_id required for non-platform-admin"
            )
        membership = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.user_id == current_user["sub"],
                    OrgMembership.org_id == str(org_id),
                    OrgMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not membership or membership.role not in (
            Role.ADMIN.value,
            Role.MANAGER.value,
            Role.TECH_SUPPORT.value,
        ):
            raise HTTPException(
                status_code=403, detail="Insufficient role to view audit log"
            )

    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if org_id:
        query = query.where(AuditLog.org_id == str(org_id))
    if action:
        query = query.where(AuditLog.action == action)
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
    if end_date:
        query = query.where(AuditLog.created_at <= end_date)

    result = await db.execute(query.offset(skip).limit(take))
    items = [
        {
            "id": str(a.id),
            "actor_type": a.actor_type,
            "actor_id": a.actor_id,
            "actor_email_snapshot": a.actor_email_snapshot,
            "action": a.action,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "org_id": a.org_id,
            "ip_address": a.ip_address,
            "metadata": a.meta,
            "created_at": a.created_at.isoformat(),
        }
        for a in result.scalars()
    ]
    return {"items": items, "skip": skip, "take": take}