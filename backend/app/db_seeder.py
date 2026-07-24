"""Database seeders for first-run / dev fixtures.

Run with:
    cd backend && uv run python -m app.db_seeder

Idempotent: re-running won't duplicate rows.
"""
from sqlalchemy import select

from app.core.security import hash_password
from app.db import async_session_maker
from app.models.platform_admin import PlatformAdmin


async def seed_platform_admin(
    email: str, password: str, full_name: str
) -> PlatformAdmin:
    """Create the first platform admin if it doesn't exist."""
    async with async_session_maker() as session:
        existing = (
            await session.execute(
                select(PlatformAdmin).where(PlatformAdmin.email == email)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        admin = PlatformAdmin(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return admin


async def main() -> None:
    import os

    email = os.environ.get("APEXAI_PLATFORM_ADMIN_EMAIL", "admin@apex.ai")
    password = os.environ.get("APEXAI_PLATFORM_ADMIN_PASSWORD", "admin123")
    full_name = os.environ.get("APEXAI_PLATFORM_ADMIN_NAME", "Platform Admin")

    admin = await seed_platform_admin(email=email, password=password, full_name=full_name)
    print(f"Seeded platform admin: {admin.email} (id={admin.id})")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())