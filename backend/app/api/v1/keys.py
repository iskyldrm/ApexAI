"""AI key vault + integration credential CRUD.

Secrets live in HashiCorp Vault at ``<scope>/<id>/<kind>-<key_id>``; DB rows
hold metadata only.
"""
import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.vault import VaultClient
from app.deps import get_current_user, get_db
from app.models.api_key import ApiKey
from app.models.integration import IntegrationCredential
from app.models.membership import OrgMembership
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyResponse,
    IntegrationCreate,
    IntegrationResponse,
)

router = APIRouter(prefix="/keys", tags=["keys"])
vault = VaultClient()


async def _require_org_admin(
    db: AsyncSession, current_user: dict, org_id: str
) -> None:
    if current_user.get("is_platform_admin"):
        return
    membership = (
        await db.execute(
            select(OrgMembership).where(
                OrgMembership.org_id == org_id,
                OrgMembership.user_id == current_user["sub"],
                OrgMembership.status == "active",
                OrgMembership.role == "admin",
            )
        )
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Org admin only")


@router.post("/ai", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_ai_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ApiKeyResponse:
    if body.org_id:
        await _require_org_admin(db, current_user, str(body.org_id))
    key_id = str(uuid4())
    scope_path = (
        f"orgs/{body.org_id}/ai-keys/{key_id}"
        if body.org_id
        else f"users/{current_user['sub']}/ai-keys/{key_id}"
    )
    await vault.write(scope_path, {"value": body.value})

    record = ApiKey(
        id=UUID(key_id),
        org_id=str(body.org_id) if body.org_id else None,
        user_id=None if body.org_id else current_user["sub"],
        provider=body.provider.value,
        label=body.label,
        vault_path=scope_path,
        is_active=True,
        created_by=current_user["sub"],
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    await audit(
        action="api_key.created",
        actor_id=current_user["sub"],
        actor_type="user",
        actor_email=current_user.get("email"),
        target_type="api_key",
        target_id=str(record.id),
        org_id=record.org_id,
        metadata={"provider": record.provider, "label": record.label},
    )

    return ApiKeyResponse(
        id=record.id,
        provider=record.provider,
        label=record.label,
        is_active=record.is_active,
        last_used_at=record.last_used_at,
        org_id=record.org_id,
        created_at=record.created_at,
    )


@router.get("/ai", response_model=list[ApiKeyResponse])
async def list_ai_keys(
    org_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[ApiKeyResponse]:
    """List AI keys for the current user, or for an org (admin only)."""
    if org_id:
        await _require_org_admin(db, current_user, str(org_id))
        query = select(ApiKey).where(ApiKey.org_id == str(org_id))
    else:
        query = select(ApiKey).where(ApiKey.user_id == current_user["sub"])
    result = await db.execute(query.order_by(ApiKey.created_at.desc()))
    return [
        ApiKeyResponse(
            id=k.id,
            provider=k.provider,
            label=k.label,
            is_active=k.is_active,
            last_used_at=k.last_used_at,
            org_id=k.org_id,
            created_at=k.created_at,
        )
        for k in result.scalars()
    ]


@router.delete("/ai/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    record = await db.get(ApiKey, str(key_id))
    if not record:
        raise HTTPException(status_code=404, detail="AI key not found")
    if record.org_id:
        await _require_org_admin(db, current_user, record.org_id)
    elif record.user_id != current_user["sub"]:
        raise HTTPException(status_code=403, detail="Not your key")
    try:
        await vault.delete(record.vault_path)
    except Exception:
        pass
    await db.delete(record)
    await db.commit()
    await audit(
        action="api_key.deleted",
        actor_id=current_user["sub"],
        actor_type="user",
        actor_email=current_user.get("email"),
        target_type="api_key",
        target_id=str(key_id),
        org_id=record.org_id,
    )


async def resolve_ai_key(
    db: AsyncSession, org_id: str, user_id: str, provider: str
) -> str:
    """User key overrides org key per spec §6.3. Returns the secret value."""
    # Try user key first
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == user_id,
            ApiKey.provider == provider,
            ApiKey.is_active == True,
        )
    )
    keys = result.scalars().all()
    if keys:
        record = keys[0]
        secret = await vault.read(record.vault_path)
        record.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        return secret["value"]
    # Fall back to org key
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.org_id == org_id,
            ApiKey.user_id.is_(None),
            ApiKey.provider == provider,
            ApiKey.is_active == True,
        )
    )
    keys = result.scalars().all()
    if keys:
        record = keys[0]
        secret = await vault.read(record.vault_path)
        record.last_used_at = datetime.now(timezone.utc)
        await db.commit()
        return secret["value"]
    raise HTTPException(
        status_code=404, detail=f"No active {provider} key for org/user"
    )


@router.post(
    "/integrations",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration(
    body: IntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> IntegrationResponse:
    if body.org_id:
        await _require_org_admin(db, current_user, str(body.org_id))
    integ_id = str(uuid4())
    scope_path = (
        f"orgs/{body.org_id}/integrations/{integ_id}"
        if body.org_id
        else f"users/{current_user['sub']}/integrations/{integ_id}"
    )
    await vault.write(scope_path, body.value)

    record = IntegrationCredential(
        id=UUID(integ_id),
        org_id=str(body.org_id) if body.org_id else None,
        user_id=None if body.org_id else current_user["sub"],
        integration_type=body.integration_type.value,
        label=body.label,
        vault_path=scope_path,
        is_active=True,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return IntegrationResponse(
        id=record.id,
        integration_type=record.integration_type,
        label=record.label,
        is_active=record.is_active,
        org_id=record.org_id,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
    )


@router.get("/integrations", response_model=list[IntegrationResponse])
async def list_integrations(
    org_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[IntegrationResponse]:
    if org_id:
        await _require_org_admin(db, current_user, str(org_id))
        query = select(IntegrationCredential).where(
            IntegrationCredential.org_id == str(org_id)
        )
    else:
        query = select(IntegrationCredential).where(
            IntegrationCredential.user_id == current_user["sub"]
        )
    result = await db.execute(query.order_by(IntegrationCredential.created_at.desc()))
    return [
        IntegrationResponse(
            id=i.id,
            integration_type=i.integration_type,
            label=i.label,
            is_active=i.is_active,
            org_id=i.org_id,
            last_used_at=i.last_used_at,
            created_at=i.created_at,
        )
        for i in result.scalars()
    ]


@router.delete(
    "/integrations/{integ_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_integration(
    integ_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    record = await db.get(IntegrationCredential, str(integ_id))
    if not record:
        raise HTTPException(status_code=404, detail="Integration not found")
    if record.org_id:
        await _require_org_admin(db, current_user, record.org_id)
    elif record.user_id != current_user["sub"]:
        raise HTTPException(status_code=403, detail="Not your integration")
    try:
        await vault.delete(record.vault_path)
    except Exception:
        pass
    await db.delete(record)
    await db.commit()