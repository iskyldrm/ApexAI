"""LiteLLM client tests — uses monkeypatch to avoid real API calls."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.llm.litellm_client import LLMResponse, LiteLLMClient


def _mock_response(
    content: str = "hello",
    tool_calls: list | None = None,
    input_tokens: int = 10,
    output_tokens: int = 5,
    finish_reason: str = "stop",
    model: str = "gpt-4o",
):
    """Build a mock litellm response object."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls or []

    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason

    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


@pytest.mark.asyncio
async def test_completion_returns_standardized_response():
    client = LiteLLMClient()
    with patch("litellm.acompletion", new=AsyncMock(return_value=_mock_response("hi"))):
        resp = await client.completion(model="gpt-4o", messages=[{"role": "user", "content": "yo"}])
    assert isinstance(resp, LLMResponse)
    assert resp.content == "hi"
    assert resp.input_tokens == 10
    assert resp.output_tokens == 5
    assert resp.cost_usd > 0  # gpt-4o has a price


@pytest.mark.asyncio
async def test_completion_extracts_tool_calls():
    tc = MagicMock()
    tc.id = "call_1"
    tc.function.name = "read_file"
    tc.function.arguments = '{"path": "/tmp/x"}'

    client = LiteLLMClient()
    with patch(
        "litellm.acompletion",
        new=AsyncMock(return_value=_mock_response(content="", tool_calls=[tc])),
    ):
        resp = await client.completion(model="gpt-4o", messages=[])
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["name"] == "read_file"
    assert resp.tool_calls[0]["arguments"] == {"path": "/tmp/x"}


@pytest.mark.asyncio
async def test_completion_fires_token_callback():
    cb = AsyncMock()
    client = LiteLLMClient(token_callback=cb)
    with patch("litellm.acompletion", new=AsyncMock(return_value=_mock_response("x"))):
        await client.completion(model="gpt-4o", messages=[])
    cb.assert_awaited_once()
    args = cb.await_args.args
    # (model, model, input_tokens, output_tokens, cost)
    assert args[0] == "gpt-4o"
    assert args[2] == 10
    assert args[3] == 5
    assert args[4] > 0


@pytest.mark.asyncio
async def test_completion_handles_api_error():
    client = LiteLLMClient()
    with patch(
        "litellm.acompletion",
        new=AsyncMock(side_effect=RuntimeError("rate limit")),
    ):
        resp = await client.completion(model="gpt-4o", messages=[])
    assert resp.finish_reason == "error"
    assert "rate limit" in resp.content


@pytest.mark.asyncio
async def test_completion_local_model_zero_cost():
    client = LiteLLMClient()
    with patch(
        "litellm.acompletion",
        new=AsyncMock(return_value=_mock_response("hi", model="ollama/llama3.2")),
    ):
        resp = await client.completion(model="ollama/llama3.2", messages=[])
    assert resp.cost_usd == 0.0


def test_estimate_cost_known_model():
    from app.agent.llm.pricing import estimate_cost

    cost = estimate_cost("gpt-4o", 1000, 500)
    # 1.0 * 0.005 + 0.5 * 0.015 = 0.005 + 0.0075 = 0.0125
    assert abs(cost - 0.0125) < 0.0001


def test_estimate_cost_unknown_model_zero():
    from app.agent.llm.pricing import estimate_cost

    assert estimate_cost("future-unknown-model", 1_000_000, 1_000_000) == 0.0


# -------------------- Provider resolution (Ollama + MiniMax) --------------------


def test_default_model_resolves_to_ollama_when_set(monkeypatch):
    """When OLLAMA_BASE_URL is set, default model is the Ollama model name."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    from app.agent.roles import resolve_default_model_name

    assert resolve_default_model_name() == "llama3.2"


def test_default_model_resolves_to_anthropic_when_ollama_absent(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "MiniMax-M3")
    from app.agent.roles import resolve_default_model_name

    assert resolve_default_model_name() == "MiniMax-M3"


def test_default_model_explicit_override_wins(monkeypatch):
    monkeypatch.setenv("APEXAI_AGENT_MODEL", "gpt-4-turbo")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
    from app.agent.roles import resolve_default_model_name

    assert resolve_default_model_name() == "gpt-4-turbo"


def test_default_model_fallback_when_no_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("APEXAI_AGENT_MODEL", raising=False)
    from app.agent.roles import resolve_default_model_name

    assert resolve_default_model_name() == "gpt-4o"


def test_client_detects_ollama_provider(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    from app.agent.llm.litellm_client import LiteLLMClient

    assert LiteLLMClient._detect_provider() == "ollama"


def test_client_detects_anthropic_provider(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-test")
    from app.agent.llm.litellm_client import LiteLLMClient

    assert LiteLLMClient._detect_provider() == "anthropic"


def test_resolve_call_kwargs_uses_ollama_base(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    from app.agent.llm.litellm_client import LiteLLMClient

    client = LiteLLMClient()
    model, key, kw = client._resolve_call_kwargs(
        "llama3.2", [{"role": "user", "content": "hi"}], None, None, {},
    )
    assert model == "ollama/llama3.2"
    assert kw["api_base"] == "http://localhost:11434/v1"
    assert kw["api_key"] == "ollama"


def test_resolve_call_kwargs_uses_anthropic_base(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.minimax.io/anthropic")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-test")
    from app.agent.llm.litellm_client import LiteLLMClient

    client = LiteLLMClient()
    model, key, kw = client._resolve_call_kwargs(
        "MiniMax-M3", [{"role": "user", "content": "hi"}], None, None, {},
    )
    assert model == "anthropic/MiniMax-M3"
    assert kw["api_base"] == "https://api.minimax.io/anthropic"
    assert kw["api_key"] == "sk-test"
