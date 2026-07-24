"""Invitation lifecycle: create, list, accept, revoke."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import audit
from app.core.security import generate_refresh_token, hash_password
from app.deps import get_current_user, get_db
from app.email_log import log_email
from app.enums import InvitationStatus, Role
from app.models.invitation import Invitation
from app.models.membership import OrgMembership, TeamMembership
from app.models.org import Org
from app.models.user import User
from app.schemas.invitation import (
    InvitationAcceptRequest,
    InvitationCreate,
    InvitationResponse,
)

settings = get_settings()
router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post(
    "/orgs/{org_id}",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    org_id: UUID,
    body: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> InvitationResponse:
    """Org admin invites a user by email + role + optional team memberships."""
    if not current_user.get("is_platform_admin"):
        membership = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.org_id == str(org_id),
                    OrgMembership.user_id == current_user["sub"],
                    OrgMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not membership or membership.role != Role.ADMIN.value:
            raise HTTPException(status_code=403, detail="Org admin only")

    org = await db.get(Org, str(org_id))
    if not org:
        raise HTTPException(status_code=404, detail="Org not found")

    plain, token_hash = generate_refresh_token()
    invitation = Invitation(
        org_id=str(org_id),
        email=body.email,
        role=body.role.value,
        team_ids=json.dumps(body.team_ids),
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.invite_ttl_days),
        status=InvitationStatus.PENDING.value,
        invited_by=current_user["sub"],
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    invite_url = f"http://localhost:3000/accept-invite?token={plain}"
    log_email(
        to=body.email,
        subject=f"Invitation to join {org.name} on ApexAI",
        body=f"Accept here: {invite_url}",
    )
    await audit(
        action="invitation.created",
        actor_id=current_user["sub"],
        actor_type="user",
        actor_email=current_user.get("email"),
        target_type="invitation",
        target_id=str(invitation.id),
        org_id=str(org_id),
    )
    return InvitationResponse(
        id=invitation.id,
        org_id=invitation.org_id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


@router.get("/orgs/{org_id}", response_model=list[InvitationResponse])
async def list_org_invitations(
    org_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[InvitationResponse]:
    if not current_user.get("is_platform_admin"):
        membership = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.org_id == str(org_id),
                    OrgMembership.user_id == current_user["sub"],
                    OrgMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not membership or membership.role != Role.ADMIN.value:
            raise HTTPException(status_code=403, detail="Org admin only")
    result = await db.execute(
        select(Invitation)
        .where(Invitation.org_id == str(org_id))
        .order_by(Invitation.created_at.desc())
    )
    return [
        InvitationResponse(
            id=i.id,
            org_id=i.org_id,
            email=i.email,
            role=i.role,
            status=i.status,
            expires_at=i.expires_at,
            created_at=i.created_at,
        )
        for i in result.scalars()
    ]


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    invitation = await db.get(Invitation, str(invitation_id))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if not current_user.get("is_platform_admin"):
        membership = (
            await db.execute(
                select(OrgMembership).where(
                    OrgMembership.org_id == invitation.org_id,
                    OrgMembership.user_id == current_user["sub"],
                    OrgMembership.status == "active",
                )
            )
        ).scalar_one_or_none()
        if not membership or membership.role != Role.ADMIN.value:
            raise HTTPException(status_code=403, detail="Org admin only")
    if invitation.status != InvitationStatus.PENDING.value:
        raise HTTPException(status_code=400, detail="Invitation already finalized")
    invitation.status = InvitationStatus.REVOKED.value
    await db.commit()


@router.post("/accept")
async def accept_invitation(
    body: InvitationAcceptRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    invitation = (
        await db.execute(
            select(Invitation).where(Invitation.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if (
        not invitation
        or invitation.status != InvitationStatus.PENDING.value
        or invitation.expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired invitation")

    user = (
        await db.execute(select(User).where(User.email == invitation.email))
    ).scalar_one_or_none()
    if not user:
        user = User(
            email=invitation.email,
            password_hash=hash_password(body.password),
            full_name=body.full_name,
            is_active=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
        await db.flush()
    else:
        user.password_hash = hash_password(body.password)
        user.is_active = True
        user.email_verified_at = datetime.now(timezone.utc)

    db.add(
        OrgMembership(
            org_id=invitation.org_id,
            user_id=str(user.id),
            role=invitation.role,
            status="active",
            joined_at=datetime.now(timezone.utc),
        )
    )

    team_ids = json.loads(invitation.team_ids or "[]")
    for team_id in team_ids:
        db.add(
            TeamMembership(
                team_id=team_id,
                user_id=str(user.id),
                team_role="member",
            )
        )

    invitation.status = InvitationStatus.ACCEPTED.value
    await db.commit()

    await audit(
        action="invitation.accepted",
        actor_id=str(user.id),
        actor_type="user",
        actor_email=user.email,
        target_type="invitation",
        target_id=str(invitation.id),
        org_id=invitation.org_id,
    )
    return {"message": "Invitation accepted", "user_id": str(user.id)}