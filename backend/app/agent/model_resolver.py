"""Resolve the default model for an agent run.

Resolution order (most specific wins):
1. Explicit ``config.model`` (request body override)
2. User-level setting: ``ai.default_model`` with scope_id = user_id
3. Org-level setting: ``ai.default_model`` with scope_id = org_id
4. Platform-level setting: ``ai.default_model`` with scope_id NULL
5. RoleConfig.default_model (built-in fallback)

If the resolved setting has ``enforced_by_admin=True``, the user-level
override is ignored.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.roles import Role, get_role_config
from app.models.setting import Setting


async def resolve_default_model(
    db: AsyncSession,
    role: Role,
    org_id: str | None,
    user_id: str | None,
    request_override: str | None = None,
) -> str:
    """Return the model name to use for this run."""
    if request_override:
        return request_override

    role_cfg = get_role_config(role)
    fallback = role_cfg.default_model

    # Look up settings in order: user > org > platform
    candidates: list[tuple[str, str | None]] = [
        ("user", user_id),
        ("org", org_id),
        ("platform", None),
    ]
    for scope, scope_id in candidates:
        if scope == "user" and not user_id:
            continue
        if scope == "org" and not org_id:
            continue
        result = await db.execute(
            select(Setting).where(
                Setting.scope == scope,
                Setting.scope_id == scope_id,
                Setting.key == "ai.default_model",
            )
        )
        setting = result.scalar_one_or_none()
        if setting is not None and setting.value:
            model = _extract_model(setting.value)
            if model:
                # Enforced-by-admin org/platform settings block user override
                if scope in ("org", "platform") and setting.enforced_by_admin:
                    return model
                if scope == "user" and not await _org_enforced(db, org_id):
                    return model
                if scope in ("org", "platform"):
                    return model  # not enforced — still wins (more specific)

    return fallback


def _extract_model(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("model") or value.get("name")
    return None


async def _org_enforced(db: AsyncSession, org_id: str | None) -> bool:
    if not org_id:
        return False
    result = await db.execute(
        select(Setting).where(
            Setting.scope == "org",
            Setting.scope_id == org_id,
            Setting.key == "ai.default_model",
        )
    )
    setting = result.scalar_one_or_none()
    return bool(setting and setting.enforced_by_admin)
