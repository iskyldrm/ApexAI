"""Redis-backed cache for LLM completions.

Caches identical chat completions by a content-derived key so repeat calls
(debug, idempotent tasks, replays) skip the LLM provider entirely. TTL is
configurable per-call; a hit returns the cached ``LLMResponse`` without
burning tokens or money.

Design choices:
- Hash key: SHA-256 of ``model + system_prompt + user_messages + tools``.
  Includes the tool schema so a tool-list change invalidates the cache.
- Stored as JSON: ``content``, ``tool_calls``, ``finish_reason``, ``input_tokens``,
  ``output_tokens``, ``cost_usd``, ``model``.
- Falls back to in-process dict if Redis is unreachable — useful for tests
  and degraded production environments.
- Per-org namespacing: cache keys include ``org_id`` so multi-tenant usage
  stays isolated.

Disabled via ``APEXAI_LLM_CACHE_DISABLED=1`` (or by passing ``enabled=False``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agent.llm.litellm_client import LLMResponse


logger = logging.getLogger(__name__)


class LLMCache:
    """LLM response cache backed by Redis (with in-memory fallback)."""

    def __init__(
        self,
        redis_url: str | None = None,
        default_ttl_seconds: int = 3600,
        enabled: bool | None = None,
    ) -> None:
        self._default_ttl = default_ttl_seconds
        # Determine enabled state from explicit arg > env
        if enabled is None:
            enabled = os.environ.get("APEXAI_LLM_CACHE_DISABLED", "").lower() not in (
                "1",
                "true",
                "yes",
            )
        self._enabled = enabled

        self._redis = None
        self._redis_url = redis_url or os.environ.get("REDIS_URL") or "redis://localhost:6380/0"

        # In-memory fallback cache (per-process). Map key -> (LLMResponse-dict, expires_at)
        import time as _t

        self._mem_cache: dict[str, tuple[dict, float]] = {}

        self._try_connect()

    def _try_connect(self) -> None:
        if not self._enabled:
            return
        try:
            import redis.asyncio as aioredis  # type: ignore

            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1,
            )
            logger.info("LLM cache: connected to Redis at %s", self._redis_url)
        except Exception as e:
            logger.warning(
                "LLM cache: Redis unavailable (%s) — using in-memory fallback", e
            )
            self._redis = None

    @staticmethod
    def make_key(
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        org_id: str | None,
    ) -> str:
        """Build a stable cache key from the LLM call inputs.

        Includes messages + tool schemas so any change in prompt or tool list
        invalidates the cache.
        """
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools or [],
            "org_id": org_id or "",
        }
        raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    async def get(self, key: str) -> LLMResponse | None:
        """Return a cached response, or None on miss / disabled."""
        if not self._enabled:
            return None

        # Try Redis first
        if self._redis is not None:
            try:
                raw = await self._redis.get(f"llm:{key}")
                if raw:
                    return self._deserialize(raw)
            except Exception as e:
                logger.debug("LLM cache: Redis get failed (%s)", e)

        # In-memory fallback
        import time

        if key in self._mem_cache:
            payload, expires_at = self._mem_cache[key]
            if expires_at > time.time():
                return self._deserialize(json.dumps(payload))
            self._mem_cache.pop(key, None)
        return None

    async def set(
        self,
        key: str,
        response: LLMResponse,
        ttl_seconds: int | None = None,
    ) -> None:
        """Store a response in the cache (best-effort)."""
        if not self._enabled:
            return

        ttl = ttl_seconds or self._default_ttl
        payload = self._serialize(response)

        if self._redis is not None:
            try:
                await self._redis.set(f"llm:{key}", payload, ex=ttl)
                return
            except Exception as e:
                logger.debug("LLM cache: Redis set failed (%s)", e)

        # In-memory fallback
        import time

        self._mem_cache[key] = (json.loads(payload), time.time() + ttl)

    @staticmethod
    def _serialize(response: LLMResponse) -> str:
        d = asdict(response)
        # ``raw`` is the original litellm Response object — not serializable.
        d.pop("raw", None)
        return json.dumps(d)

    @staticmethod
    def _deserialize(raw: str):
        # Local import to avoid circular dependency at module load time.
        from app.agent.llm.litellm_client import LLMResponse

        d = json.loads(raw)
        return LLMResponse(
            content=d.get("content", ""),
            tool_calls=d.get("tool_calls", []),
            finish_reason=d.get("finish_reason", "stop"),
            input_tokens=d.get("input_tokens", 0),
            output_tokens=d.get("output_tokens", 0),
            cost_usd=d.get("cost_usd", 0.0),
            model=d.get("model", ""),
        )

    async def clear(self) -> None:
        """Drop all cached entries (Redis + in-memory)."""
        self._mem_cache.clear()
        if self._redis is not None:
            try:
                # We can't FLUSHDB safely (might nuke other namespaces), so
                # best-effort SCAN + delete for our prefix only.
                async for k in self._redis.scan_iter("llm:*"):
                    await self._redis.delete(k)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Singleton + wiring
# ---------------------------------------------------------------------------


_singleton: LLMCache | None = None


def get_llm_cache() -> LLMCache:
    """Lazy singleton accessor."""
    global _singleton
    if _singleton is None:
        _singleton = LLMCache()
    return _singleton


def reset_llm_cache_for_tests() -> None:
    """Test helper: drop the singleton + clear caches."""
    global _singleton
    _singleton = None