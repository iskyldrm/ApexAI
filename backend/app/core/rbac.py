import inspect
from functools import wraps
from typing import Callable

from fastapi import HTTPException, status

from app.enums import Permission, Role, TeamRole, has_permission


def _resolve_kwargs(func: Callable, args: tuple, kwargs: dict) -> dict:
    """Bind *args, **kwargs against func signature to get resolved kwargs,
    including parameter defaults. Lets the decorator inspect role values that
    the wrapped function declares as default arguments (e.g. test fixtures)."""
    try:
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except TypeError:
        return dict(kwargs)


def require_permission(permission: Permission) -> Callable:
    """Decorator: user must have the given permission via their role.

    Expects the wrapped function to expose ``user_role`` (Role) and
    ``is_platform_admin`` (bool) — either as parameters or kwargs.
    Platform admins bypass the check.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            resolved = _resolve_kwargs(func, args, kwargs)
            user_role: Role | None = resolved.get("user_role")
            is_platform_admin: bool = resolved.get("is_platform_admin", False)
            if is_platform_admin:
                return await func(*args, **kwargs)
            if user_role is None or not has_permission(user_role, permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing permission: {permission.value}",
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_org_role(allowed_roles: list[Role]) -> Callable:
    """Decorator: user must have one of the given org roles (or be platform admin)."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            resolved = _resolve_kwargs(func, args, kwargs)
            user_role: Role | None = resolved.get("user_role")
            is_platform_admin: bool = resolved.get("is_platform_admin", False)
            if is_platform_admin or (user_role in allowed_roles):
                return await func(*args, **kwargs)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {[r.value for r in allowed_roles]}",
            )

        return wrapper

    return decorator


def require_team_role(allowed_roles: list[TeamRole]) -> Callable:
    """Decorator: user must have one of the given team roles for the team."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            resolved = _resolve_kwargs(func, args, kwargs)
            user_team_roles: list[TeamRole] = resolved.get("user_team_roles", [])
            is_platform_admin: bool = resolved.get("is_platform_admin", False)
            if is_platform_admin or any(r in allowed_roles for r in user_team_roles):
                return await func(*args, **kwargs)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required team role: {[r.value for r in allowed_roles]}",
            )

        return wrapper

    return decorator