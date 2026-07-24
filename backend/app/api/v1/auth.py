"""Auth endpoints: login, refresh, logout, register, forgot/reset password, /me.

Tokens are stored in HttpOnly cookies (CSRF protection deferred to Phase 6
when the frontend is wired up). On login the same tokens are also returned
in the JSON body so non-browser clients can pick them up.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import audit
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    verify_password,
)
from app.deps import get_current_user, get_db
from app.email_log import log_email
from app.enums import Role
from app.models.auth_token import PasswordResetToken, RefreshToken
from app.models.membership import OrgMembership
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


async def _build_orgs(db: AsyncSession, user_id: str) -> list[dict]:
    result = await db.execute(
        select(OrgMembership).where(OrgMembership.user_id == user_id)
    )
    return [
        {"org_id": m.org_id, "role": m.role, "teams": []}
        for m in result.scalars()
        if m.status == "active"
    ]


def _set_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie(
        "access_token",
        access,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_access_ttl_minutes * 60,
    )
    response.set_cookie(
        "refresh_token",
        refresh,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_refresh_ttl_days * 86400,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Self-service registration. Creates a User (no org) and returns tokens."""
    existing = (
        await db.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await audit(
        action="user.registered",
        actor_id=str(user.id),
        actor_type="user",
        actor_email=user.email,
    )

    access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        is_platform_admin=False,
        orgs=[],
    )
    plain_refresh, refresh_hash = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=str(user.id),
            token_hash=refresh_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    await db.commit()

    _set_cookies(response, access, plain_refresh)
    return TokenResponse(
        access_token=access,
        refresh_token=plain_refresh,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = (
        await db.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    orgs = await _build_orgs(db, str(user.id))

    access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        is_platform_admin=False,
        orgs=orgs,
    )
    plain_refresh, refresh_hash = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=str(user.id),
            token_hash=refresh_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    await audit(
        action="user.login",
        actor_id=str(user.id),
        actor_type="user",
        actor_email=user.email,
    )

    _set_cookies(response, access, plain_refresh)
    return TokenResponse(
        access_token=access,
        refresh_token=plain_refresh,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing"
        )
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    record = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if not record or record.revoked_at or record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    user = await db.get(User, record.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    orgs = await _build_orgs(db, str(user.id))
    access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        is_platform_admin=False,
        orgs=orgs,
    )

    # Rotate: revoke old, issue new
    record.revoked_at = datetime.now(timezone.utc)
    plain_new, new_hash = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=str(user.id),
            token_hash=new_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    await db.commit()

    _set_cookies(response, access, plain_new)
    return TokenResponse(
        access_token=access,
        refresh_token=plain_new,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )


@router.post("/logout")
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: Annotated[str | None, Cookie(alias="refresh_token")] = None,
    current_user: dict = Depends(get_current_user),
) -> dict:
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        record = (
            await db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        if record and not record.revoked_at:
            record.revoked_at = datetime.now(timezone.utc)
            await db.commit()

    await audit(
        action="user.logout",
        actor_id=current_user.get("sub"),
        actor_type="user",
        actor_email=current_user.get("email"),
    )

    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out"}


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Always return the same message — don't leak whether the email exists."""
    user = (
        await db.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    generic = {
        "message": "If the email is registered, a reset link has been sent."
    }
    if not user:
        return generic

    plain, token_hash = generate_refresh_token()
    db.add(
        PasswordResetToken(
            user_id=str(user.id),
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=settings.password_reset_ttl_minutes),
        )
    )
    await db.commit()

    reset_url = f"http://localhost:3000/reset-password?token={plain}"
    log_email(
        to=user.email,
        subject="Reset your ApexAI password",
        body=f"Click to reset: {reset_url}",
    )
    return generic


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    record = (
        await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if (
        not record
        or record.used_at
        or record.expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    user = await db.get(User, record.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )
    user.password_hash = hash_password(body.new_password)
    record.used_at = datetime.now(timezone.utc)
    await db.commit()

    await audit(
        action="user.password_reset",
        actor_id=str(user.id),
        actor_type="user",
        actor_email=user.email,
    )
    return {"message": "Password successfully reset"}


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)) -> dict:
    return {
        "id": current_user.get("sub"),
        "email": current_user.get("email"),
        "is_platform_admin": current_user.get("is_platform_admin", False),
        "orgs": current_user.get("orgs", []),
    }