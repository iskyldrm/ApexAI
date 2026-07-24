import pytest

from app.core.vault import VaultClient


@pytest.mark.asyncio
async def test_vault_write_and_read():
    client = VaultClient()
    await client.write("test/foo", {"value": "bar"})
    result = await client.read("test/foo")
    assert result == {"value": "bar"}
    await client.delete("test/foo")


@pytest.mark.asyncio
async def test_vault_read_missing_returns_empty():
    client = VaultClient()
    # Cleanup any leftover from a previous failed run
    try:
        await client.delete("test/missing")
    except Exception:
        pass
    result = await client.read("test/missing")
    assert result == {}