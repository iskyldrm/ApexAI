from typing import Annotated

from fastapi import Cookie, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session

settings = get_settings()


async def get_db() -> AsyncSession:
    async with get_session() as session:
        yield session


async def get_current_user(
    access_token: Annotated[str | None, Cookie(alias="access_token")] = None,
) -> dict:
    """Extract JWT from cookie, verify, return claims."""
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token missing",
        )
    try:
        return jwt.decode(
            access_token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


async def get_optional_user(
    access_token: Annotated[str | None, Cookie(alias="access_token")] = None,
) -> dict | None:
    if not access_token:
        return None
    try:
        return jwt.decode(
            access_token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None