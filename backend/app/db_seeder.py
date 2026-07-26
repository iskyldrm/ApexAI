"""Database seeders for first-run / dev fixtures.

Run with:
    cd backend && uv run python -m app.db_seeder

Idempotent: re-running won't duplicate rows.

The platform admin needs to exist in BOTH the ``users`` table (so the
auth flow can verify the password and issue JWTs) AND the
``platform_admins`` table (so the orgs/keys audit routes can check
``is_platform_admin``). This seeder keeps the two in sync.
"""
import os

from sqlalchemy import select

from app.core.security import hash_password
from app.db import async_session_maker
from app.models.platform_admin import PlatformAdmin
from app.models.user import User


async def seed_platform_admin(
    email: str, password: str, full_name: str
) -> User:
    """Create the first platform admin if it doesn't exist.

    Inserts into both ``users`` (for login) and ``platform_admins``
    (for the admin flag) tables. Returns the User row.
    """
    async with async_session_maker() as session:
        # 1. Ensure a User row exists
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                is_active=True,
                email_verified_at=__import__("datetime").datetime.utcnow(),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # Update password so re-runs reset it
            user.password_hash = hash_password(password)
            await session.commit()
            await session.refresh(user)

        # 2. Ensure a PlatformAdmin row exists for the same email
        admin = (
            await session.execute(
                select(PlatformAdmin).where(PlatformAdmin.email == email)
            )
        ).scalar_one_or_none()
        if admin is None:
            admin = PlatformAdmin(
                email=email,
                password_hash=user.password_hash,
                full_name=full_name,
            )
            session.add(admin)
            await session.commit()
            await session.refresh(admin)

        return user


async def main() -> None:
    email = os.environ.get("APEXAI_PLATFORM_ADMIN_EMAIL", "admin@apex.ai")
    password = os.environ.get("APEXAI_PLATFORM_ADMIN_PASSWORD", "admin123")
    full_name = os.environ.get("APEXAI_PLATFORM_ADMIN_NAME", "Platform Admin")

    user = await seed_platform_admin(email=email, password=password, full_name=full_name)
    print(f"Seeded platform admin: {user.email} (user id={user.id})")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
