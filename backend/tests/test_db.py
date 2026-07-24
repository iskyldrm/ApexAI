import pytest
from sqlalchemy import text

from app.db import get_session


@pytest.mark.asyncio
async def test_database_connection():
    """Verify we can connect to Postgres and execute a trivial query."""
    async with get_session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
