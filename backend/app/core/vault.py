import hvac
from hvac.exceptions import InvalidPath

from app.config import get_settings

settings = get_settings()


class VaultClient:
    """HashiCorp Vault KV v2 client. Synchronous hvac wrapped in async API.

    The hvac client is thread-safe and uses HTTP under the hood — exposing
    it as async keeps call-sites simple without blocking the event loop on
    single-request lifecycles (hvac returns quickly for local dev).
    """

    def __init__(self) -> None:
        self._client = hvac.Client(url=settings.vault_url, token=settings.vault_token)
        if not self._client.is_authenticated():
            raise RuntimeError("Vault authentication failed")
        self._mount = settings.vault_mount_point

    async def read(self, path: str) -> dict:
        try:
            response = self._client.secrets.kv.v2.read_secret_version(
                path=path, mount_point=self._mount, raise_on_deleted_version=False
            )
        except InvalidPath:
            return {}
        if response is None:
            return {}
        return response["data"]["data"]

    async def write(self, path: str, data: dict) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path=path, secret=data, mount_point=self._mount
        )

    async def delete(self, path: str) -> None:
        self._client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=path, mount_point=self._mount
        )