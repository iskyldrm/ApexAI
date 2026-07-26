"""Settings endpoints with override-chain resolution.

Order (most specific → most general):
user → team → org → platform
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.enums import SettingScope
from app.models.membership import OrgMembership, TeamMembership
from app.models.setting import Setting
from app.schemas.setting import SettingResponse, SettingSetRequest

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> SettingResponse:
    """Resolve via override chain: user → team → org → platform."""
    candidates: list[tuple[str, str | None]] = [
        (SettingScope.USER.value, current_user["sub"])
    ]
    org_ids: list[str] = []
    for org in current_user.get("orgs", []):
        org_id = org["org_id"]
        org_ids.append(org_id)
        for team_id in org.get("teams", []):
            candidates.append((SettingScope.TEAM.value, team_id))
        candidates.append((SettingScope.ORG.value, org_id))
    candidates.append((SettingScope.PLATFORM.value, None))

    for scope, scope_id in candidates:
        query = select(Setting).where(Setting.scope == scope, Setting.key == key)
        if scope_id:
            query = query.where(Setting.scope_id == scope_id)
        else:
            query = query.where(Setting.scope_id.is_(None))
        result = await db.execute(query)
        setting = result.scalar_one_or_none()
        if setting:
            return SettingResponse(
                scope=setting.scope,
                scope_id=setting.scope_id,
                key=setting.key,
                value=setting.value,
                enforced_by_admin=setting.enforced_by_admin,
                updated_by=setting.updated_by,
                updated_at=setting.updated_at,
            )
    raise HTTPException(status_code=404, detail="Setting not found")


@router.put("/{key}")
async def set_setting(
    key: str,
    body: SettingSetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Upsert a setting at the specified scope."""
    if body.scope == SettingScope.PLATFORM and not current_user.get(
        "is_platform_admin"
    ):
        raise HTTPException(status_code=403, detail="Platform admin required")

    if body.scope == SettingScope.ORG:
        if not body.scope_id:
            raise HTTPException(status_code=400, detail="scope_id required for org scope")
        if current_user.get("is_platform_admin"):
            pass  # platform admin bypass
        else:
            membership = (
                await db.execute(
                    select(OrgMembership).where(
                        OrgMembership.org_id == body.scope_id,
                        OrgMembership.user_id == current_user["sub"],
                        OrgMembership.status == "active",
                    )
                )
            ).scalar_one_or_none()
            if not membership or membership.role != "admin":
                raise HTTPException(status_code=403, detail="Org admin required")

    if body.scope == SettingScope.TEAM:
        if not body.scope_id:
            raise HTTPException(status_code=400, detail="scope_id required for team scope")
        membership = (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == body.scope_id,
                    TeamMembership.user_id == current_user["sub"],
                )
            )
        ).scalar_one_or_none()
        if not membership and not current_user.get("is_platform_admin"):
            raise HTTPException(status_code=403, detail="Team membership required")

    if body.scope == SettingScope.USER and body.scope_id and body.scope_id != current_user["sub"]:
        raise HTTPException(status_code=400, detail="Can only set own user scope")

    stmt = pg_insert(Setting).values(
        scope=body.scope.value,
        scope_id=body.scope_id,
        key=key,
        value=body.value,
        enforced_by_admin=body.enforced_by_admin,
        updated_by=current_user["sub"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["scope", "scope_id", "key"],
        set_={
            "value": body.value,
            "enforced_by_admin": body.enforced_by_admin,
            "updated_by": current_user["sub"],
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"message": "Setting updated", "key": key}


@router.delete("/{key}", status_code=204)
async def delete_setting(
    key: str,
    scope: SettingScope,
    scope_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> None:
    if scope == SettingScope.PLATFORM and not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin required")
    query = select(Setting).where(
        Setting.scope == scope.value, Setting.key == key
    )
    if scope_id:
        query = query.where(Setting.scope_id == scope_id)
    else:
        query = query.where(Setting.scope_id.is_(None))
    setting = (await db.execute(query)).scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    await db.delete(setting)
    await db.commit()