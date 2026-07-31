"""Tests for the LLM cache."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.cache import LLMCache, get_llm_cache, reset_llm_cache_for_tests
from app.agent.llm.litellm_client import LLMResponse, LiteLLMClient


def _make_response(content: str = "cached", input_tokens: int = 10, output_tokens: int = 5) -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[],
        finish_reason="stop",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=0.001,
        model="gpt-4o",
    )


# -------------------- Pure cache tests (no LLM) --------------------


@pytest.fixture(autouse=True)
def _reset_cache_singleton():
    """Each test starts with a fresh cache singleton."""
    reset_llm_cache_for_tests()
    yield
    reset_llm_cache_for_tests()


def test_make_key_is_deterministic():
    key1 = LLMCache.make_key(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        org_id="org1",
    )
    key2 = LLMCache.make_key(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        org_id="org1",
    )
    assert key1 == key2
    assert len(key1) == 64  # sha256 hex digest length


def test_make_key_changes_with_messages():
    a = LLMCache.make_key(model="m", messages=[{"role": "user", "content": "a"}], tools=None, org_id=None)
    b = LLMCache.make_key(model="m", messages=[{"role": "user", "content": "b"}], tools=None, org_id=None)
    assert a != b


def test_make_key_changes_with_tools():
    a = LLMCache.make_key(model="m", messages=[], tools=None, org_id=None)
    b = LLMCache.make_key(model="m", messages=[], tools=[{"name": "t1"}], org_id=None)
    assert a != b


def test_make_key_changes_with_org():
    a = LLMCache.make_key(model="m", messages=[], tools=None, org_id="org1")
    b = LLMCache.make_key(model="m", messages=[], tools=None, org_id="org2")
    assert a != b


@pytest.mark.asyncio
async def test_set_and_get_in_memory_fallback():
    """With Redis unavailable, the cache uses an in-memory dict."""
    cache = LLMCache(enabled=True)
    cache._redis = None  # force fallback
    response = _make_response("hello")
    key = LLMCache.make_key(model="m", messages=[], tools=None, org_id=None)
    await cache.set(key, response)
    got = await cache.get(key)
    assert got is not None
    assert got.content == "hello"
    assert got.input_tokens == 10


@pytest.mark.asyncio
async def test_get_returns_none_on_miss():
    cache = LLMCache(enabled=True)
    cache._redis = None
    key = LLMCache.make_key(model="m", messages=[], tools=None, org_id=None)
    assert await cache.get(key) is None


@pytest.mark.asyncio
async def test_get_returns_none_when_disabled():
    cache = LLMCache(enabled=False)
    response = _make_response("nope")
    key = LLMCache.make_key(model="m", messages=[], tools=None, org_id=None)
    await cache.set(key, response)
    assert await cache.get(key) is None


@pytest.mark.asyncio
async def test_clear_drops_memory_cache():
    cache = LLMCache(enabled=True)
    cache._redis = None
    response = _make_response()
    key = LLMCache.make_key(model="m", messages=[], tools=None, org_id=None)
    await cache.set(key, response)
    assert await cache.get(key) is not None
    await cache.clear()
    assert await cache.get(key) is None


# -------------------- LiteLLMClient integration --------------------


@pytest.mark.asyncio
async def test_llm_client_uses_cache_on_second_call():
    """Second identical call must NOT call litellm.acompletion."""
    # Pre-populate cache with a response
    reset_llm_cache_for_tests()
    cache = LLMCache(enabled=True)
    cache._redis = None  # in-memory only for tests
    reset_llm_cache_for_tests()

    # Recreate with the test cache
    from app.agent.cache import _singleton as cache_singleton  # noqa: F401

    # Set singleton to our test cache
    import app.agent.cache as cache_mod

    cache_mod._singleton = cache

    # Cache the response under the same key the client will compute
    messages = [{"role": "user", "content": "hi"}]
    tools = None
    model = "gpt-4o"
    org_id = "org-x"
    key = LLMCache.make_key(model=model, messages=messages, tools=tools, org_id=org_id)
    await cache.set(key, _make_response("from cache", input_tokens=99, output_tokens=11))

    # Now create a client — should hit the cache
    client = LiteLLMClient(cache=cache)
    with patch("litellm.acompletion", new_callable=AsyncMock) as mock:
        response = await client.completion(
            model=model, messages=messages, tools=tools, org_id=org_id
        )

    # litellm must NOT have been called
    mock.assert_not_called()
    assert response.content == "from cache"
    assert response.input_tokens == 99


@pytest.mark.asyncio
async def test_llm_client_calls_provider_on_cache_miss():
    """First call with an empty cache should hit the provider."""
    import app.agent.cache as cache_mod

    cache = LLMCache(enabled=True)
    cache._redis = None
    cache_mod._singleton = cache

    client = LiteLLMClient(cache=cache)

    # Build a fake litellm response
    fake_choice = MagicMock()
    fake_choice.finish_reason = "stop"
    fake_msg = MagicMock()
    fake_msg.content = "fresh"
    fake_msg.tool_calls = None
    fake_choice.message = fake_msg

    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 7
    fake_usage.completion_tokens = 3

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_response.usage = fake_usage

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock:
        mock.return_value = fake_response
        response = await client.completion(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            org_id=None,
        )

    mock.assert_called_once()
    assert response.content == "fresh"
    assert response.input_tokens == 7


@pytest.mark.asyncio
async def test_llm_client_caches_response_after_provider_call():
    """After a successful provider call, the response must be cached."""
    import app.agent.cache as cache_mod

    cache = LLMCache(enabled=True)
    cache._redis = None
    cache_mod._singleton = cache

    client = LiteLLMClient(cache=cache)

    fake_choice = MagicMock()
    fake_choice.finish_reason = "stop"
    fake_msg = MagicMock()
    fake_msg.content = "cached-after"
    fake_msg.tool_calls = None
    fake_choice.message = fake_msg

    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 5
    fake_usage.completion_tokens = 2

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_response.usage = fake_usage

    messages = [{"role": "user", "content": "unique-msg-1"}]
    with patch("litellm.acompletion", new_callable=AsyncMock) as mock:
        mock.return_value = fake_response
        await client.completion(model="gpt-4o", messages=messages)

    # Cache should now contain the response
    key = LLMCache.make_key(
        model="gpt-4o", messages=messages, tools=None, org_id=None
    )
    cached = await cache.get(key)
    assert cached is not None
    assert cached.content == "cached-after"


@pytest.mark.asyncio
async def test_llm_client_can_run_without_cache():
    """If cache=None is passed to the client, no cache operations happen."""
    client = LiteLLMClient(cache=None)

    fake_choice = MagicMock()
    fake_choice.finish_reason = "stop"
    fake_msg = MagicMock()
    fake_msg.content = "no cache"
    fake_msg.tool_calls = None
    fake_choice.message = fake_msg

    fake_usage = MagicMock()
    fake_usage.prompt_tokens = 1
    fake_usage.completion_tokens = 1

    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_response.usage = fake_usage

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock:
        mock.return_value = fake_response
        response = await client.completion(model="gpt-4o", messages=[{"role": "user", "content": "x"}])

    assert response.content == "no cache"
    mock.assert_called_once()