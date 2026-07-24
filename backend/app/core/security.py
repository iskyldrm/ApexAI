import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


def hash_password(plain: str) -> str:
    """Hash password using bcrypt with cost 12."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: str,
    email: str,
    is_platform_admin: bool,
    orgs: list[dict],
    ttl_minutes: int | None = None,
) -> str:
    """Create a JWT access token (15 min default)."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ttl_minutes or settings.jwt_access_ttl_minutes)
    payload = {
        "sub": user_id,
        "email": email,
        "is_platform_admin": is_platform_admin,
        "orgs": orgs,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_refresh_token() -> tuple[str, str]:
    """Generate a refresh token. Returns (plain, sha256_hash)."""
    plain = secrets.token_urlsafe(48)
    h = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return plain, h