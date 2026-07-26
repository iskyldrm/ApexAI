"""Org CRUD (platform-admin-scoped) and team CRUD (org-admin-scoped).

Endpoints:
- POST   /api/v1/orgs                   — platform admin creates org
- GET    /api/v1/orgs                   — platform admin lists all orgs
- GET    /api/v1/orgs/{org_id}          — platform admin or org member reads
- PATCH  /api/v1/orgs/{org_id}          — org admin updates
- DELETE /api/v1/orgs/{org_id}          — platform admin soft-deletes (status='deleted')
- POST   /api/v1/orgs/{org_id}/teams    — org admin creates team
- GET    /api/v1/orgs/{org_id}/teams    — any org member lists teams
- PATCH  /api/v1/orgs/{org_id}/teams/{team_id}
- DELETE /api/v1/orgs/{org_id}/teams/{team_id}
"""
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.security import hash_password
from app.deps import get_current_user, get_db
from app.enums import OrgStatus, Role
from app.models.membership import OrgMembership
from app.models.org import Org
from app.models.team import Team
from app.models.user import User
from app.schemas.org import (
    OrgCreate,
    OrgResponse,
    OrgUpdate,
    TeamCreate,
    TeamResponse,
    TeamUpdate,
)

router = APIRouter(prefix="/orgs", tags=["orgs"])


async def _require_org_member(
    db: AsyncSession, current_user: dict, org_id: UUID
) -> OrgMembership:
    if current_user.get("is_platform_admin"):
        # Platform admin bypasses membership check but still returns a stub
        return OrgMembership(
            org_id=str(org_id),
            user_id=current_user["sub"],
            role=Role.ADMIN.value,
            status="active",
        )
    membership = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.org_id == str(org_id),
                OrgMembership.user_id == current_user["sub"],
            )
        )
    ).scalar_one_or_none()
    if not membership or membership.status != "active":
        raise HTTPException(status_code=403, detail="Not an active org member")
    return membership


async def _require_org_admin(
    db: AsyncSession, current_user: dict, org_id: UUID
) -> OrgMembership:
    membership = await _require_org_member(db, current_user, org_id)
    if membership.role != Role.ADMIN.value and not current_user.get(
        "is_platform_admin"
    ):
        raise HTTPException(status_code=403, detail="Org admin role required")
    return membership


@router.post("", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_org(
    body: OrgCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> OrgResponse:
    """Platform admin only — creates an org + initial admin user."""
    if not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin only")

    org = Org(slug=body.slug, name=body.name, status=OrgStatus.ACTIVE.value)
    db.add(org)
    await db.flush()

    admin_user = (
        await db.execute(select(User).where(User.email == body.admin_email))
    ).scalar_one_or_none()
    if not admin_user:
        admin_user = User(
            email=body.admin_email,
            password_hash=hash_password("change-me-on-first-login"),
            full_name=body.admin_full_name,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(admin_user)
        await db.flush()

    db.add(
        OrgMembership(
            org_id=str(org.id),
            user_id=str(admin_user.id),
            role=Role.ADMIN.value,
            status="active",
            joined_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    await db.refresh(org)

    await audit(
        action="org.created",
        actor_id=current_user["sub"],
        actor_type="platform_admin",
        actor_email=current_user.get("email"),
        target_type="org",
        target_id=str(org.id),
        org_id=str(org.id),
    )

    return OrgResponse(
        id=org.id,
        slug=org.slug,
        name=org.name,
        status=org.status,
        created_at=org.created_at,
    )


@router.get("", response_model=list[OrgResponse])
async def list_orgs(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[OrgResponse]:
    if not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin only")
    result = await db.execute(select(Org).order_by(Org.created_at.desc()))
    return [
        OrgResponse(
            id=o.id, slug=o.slug, name=o.name, status=o.status, created_at=o.created_at
        )
        for o in result.scalars()
    ]


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> OrgResponse:
    if not current_user.get("is_platform_admin"):
        await _require_org_member(db, current_user, org_id)
    org = await db.get(Org, str(org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")
    return OrgResponse(
        id=org.id, slug=org.slug, name=org.name, status=org.status, created_at=org.created_at
    )


@router.patch("/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: UUID,
    body: OrgUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> OrgResponse:
    await _require_org_admin(db, current_user, org_id)
    org = await db.get(Org, str(org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")
    if body.name is not None:
        org.name = body.name
    if body.status is not None:
        org.status = body.status
    await db.commit()
    await db.refresh(org)
    await audit(
        action="org.updated",
        actor_id=current_user["sub"],
        actor_type="user",
        actor_email=current_user.get("email"),
        target_type="org",
        target_id=str(org.id),
        org_id=str(org.id),
        metadata=body.model_dump(exclude_none=True),
    )
    return OrgResponse(
        id=org.id, slug=org.slug, name=org.name, status=org.status, created_at=org.created_at
    )


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    if not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin only")
    org = await db.get(Org, str(org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")
    org.status = OrgStatus.DELETED.value
    await db.commit()
    await audit(
        action="org.deleted",
        actor_id=current_user["sub"],
        actor_type="platform_admin",
        actor_email=current_user.get("email"),
        target_type="org",
        target_id=str(org.id),
    )


@router.post(
    "/{org_id}/teams",
    response_model=TeamResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_team(
    org_id: UUID,
    body: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> TeamResponse:
    await _require_org_admin(db, current_user, org_id)
    team = Team(
        org_id=str(org_id),
        name=body.name,
        slug=body.slug,
        description=body.description,
        created_by=current_user["sub"],
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return TeamResponse(
        id=team.id,
        org_id=team.org_id,
        name=team.name,
        slug=team.slug,
        description=team.description,
        created_at=team.created_at,
    )


@router.get("/{org_id}/teams", response_model=list[TeamResponse])
async def list_teams(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[TeamResponse]:
    if not current_user.get("is_platform_admin"):
        await _require_org_member(db, current_user, org_id)
    result = await db.execute(
        select(Team).where(Team.org_id == str(org_id)).order_by(Team.created_at.desc())
    )
    return [
        TeamResponse(
            id=t.id,
            org_id=t.org_id,
            name=t.name,
            slug=t.slug,
            description=t.description,
            created_at=t.created_at,
        )
        for t in result.scalars()
    ]


@router.patch(
    "/{org_id}/teams/{team_id}", response_model=TeamResponse
)
async def update_team(
    org_id: UUID,
    team_id: UUID,
    body: TeamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> TeamResponse:
    await _require_org_admin(db, current_user, org_id)
    team = await db.get(Team, str(team_id))
    if not team or team.org_id != str(org_id):
        raise HTTPException(status_code=404, detail="Team not found")
    if body.name is not None:
        team.name = body.name
    if body.description is not None:
        team.description = body.description
    await db.commit()
    await db.refresh(team)
    return TeamResponse(
        id=team.id,
        org_id=team.org_id,
        name=team.name,
        slug=team.slug,
        description=team.description,
        created_at=team.created_at,
    )


@router.delete(
    "/{org_id}/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_team(
    org_id: UUID,
    team_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    await _require_org_admin(db, current_user, org_id)
    team = await db.get(Team, str(team_id))
    if not team or team.org_id != str(org_id):
        raise HTTPException(status_code=404, detail="Team not found")
    await db.delete(team)
    await db.commit()