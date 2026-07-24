import pytest

from app.db_seeder import seed_platform_admin


@pytest.mark.asyncio
async def test_seed_platform_admin_creates_first_admin():
    admin = await seed_platform_admin(
        email="seed-test@apex.ai",
        password="seed-password-123",
        full_name="Seeded Admin",
    )
    assert admin.email == "seed-test@apex.ai"
    assert admin.password_hash != "seed-password-123"  # Hashed
    assert admin.full_name == "Seeded Admin"


@pytest.mark.asyncio
async def test_seed_platform_admin_is_idempotent():
    admin1 = await seed_platform_admin(
        email="idempotent@apex.ai",
        password="pw1",
        full_name="Admin 1",
    )
    admin2 = await seed_platform_admin(
        email="idempotent@apex.ai",
        password="pw2",
        full_name="Admin 2",
    )
    # Same email → same row, password NOT overwritten
    assert admin1.id == admin2.id
    assert admin2.full_name == "Admin 1"  # original preserved