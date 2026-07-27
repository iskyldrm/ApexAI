"""LiteLLM client wrapper with token tracking + cost calculation.

Wraps ``litellm.completion`` so the rest of the agent runtime depends
on a small, mockable surface (``completion() -> LLMResponse``).

Token usage is recorded in a callback so each LLM call can be persisted
to the ``token_usage`` table by the agent loop (F infrastructure).

Provider resolution is env-driven:
- ``OLLAMA_BASE_URL`` → Ollama (OpenAI-compatible) at /v1
- ``ANTHROPIC_BASE_URL`` + ``ANTHROPIC_AUTH_TOKEN`` → Anthropic-compatible
  (your MiniMax or any other gateway)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from app.agent.llm.pricing import estimate_cost


@dataclass
class LLMResponse:
    """Standardized response shape across providers."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str = "stop"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    raw: Any = None


# Type alias for the token-tracking callback
TokenCallback = Callable[[str, str, int, int, float], Awaitable[None]]


class LiteLLMClient:
    """Thin async wrapper around ``litellm.acompletion``.

    Provider resolution (env-driven):
    - If ``OLLAMA_BASE_URL`` is set: provider is ``ollama/`` (OpenAI-compatible)
    - Else if ``ANTHROPIC_BASE_URL`` + ``ANTHROPIC_AUTH_TOKEN``: provider is
      ``anthropic/`` (used for MiniMax or any Anthropic-compatible gateway)
    - Otherwise: provider is whatever the model string says (e.g. ``gpt-4o``)
    """

    def __init__(self, token_callback: TokenCallback | None = None) -> None:
        self._callback = token_callback
        self._provider = self._detect_provider()

    @staticmethod
    def _detect_provider() -> str:
        if os.environ.get("OLLAMA_BASE_URL"):
            return "ollama"
        if os.environ.get("ANTHROPIC_BASE_URL") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return "anthropic"
        return ""

    def _resolve_call_kwargs(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        api_key: str | None,
        kwargs: dict,
    ) -> tuple[str, str, dict]:
        """Return (litellm_model, resolved_api_key, call_kwargs).

        Strips any existing provider prefix on ``model`` and re-applies
        the env-driven one. Passes ``api_base`` + ``api_key`` based on env.
        """
        bare = model.split("/", 1)[-1] if "/" in model else model
        call_kwargs: dict = {"messages": messages}
        if tools:
            call_kwargs["tools"] = tools
        if self._provider == "ollama":
            litellm_model = f"ollama/{bare}"
            base = os.environ["OLLAMA_BASE_URL"].rstrip("/")
            # Ollama serves OpenAI-compatible at /v1
            if not base.endswith("/v1"):
                base = base + "/v1"
            call_kwargs["api_base"] = base
            call_kwargs["api_key"] = api_key or os.environ.get("OLLAMA_API_KEY", "ollama")
        elif self._provider == "anthropic":
            litellm_model = f"anthropic/{bare}"
            call_kwargs["api_base"] = os.environ["ANTHROPIC_BASE_URL"]
            call_kwargs["api_key"] = api_key or os.environ["ANTHROPIC_AUTH_TOKEN"]
        else:
            litellm_model = model
            if api_key:
                call_kwargs["api_key"] = api_key
        call_kwargs.update(kwargs)
        resolved_key = call_kwargs.get("api_key", "")
        return litellm_model, resolved_key, call_kwargs

    async def completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a chat completion. Returns an LLMResponse.

        Provider is auto-detected from env (Ollama > Anthropic-compat > raw).
        Explicit ``api_key`` overrides the env-derived one.
        """
        import litellm

        litellm_model, _resolved_key, call_kwargs = self._resolve_call_kwargs(
            model, messages, tools, api_key, kwargs
        )

        try:
            response = await litellm.acompletion(**call_kwargs)
        except Exception as e:
            # Return an error response instead of raising — the agent loop
            # will see finish_reason="error" and decide what to do
            return LLMResponse(
                content=f"LLM error: {e}",
                finish_reason="error",
                model=litellm_model,
            )

        # Extract the first choice
        choice = response.choices[0]
        msg = choice.message
        tool_calls = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                # Arguments may be JSON string
                args = tc.function.arguments
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    }
                )

        # Token usage
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        cost = estimate_cost(model, input_tokens, output_tokens)

        # Fire token callback if registered
        if self._callback is not None:
            try:
                await self._callback(model, model, input_tokens, output_tokens, cost)
            except Exception:
                pass  # never let callback errors break the LLM call

        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            finish_reason=getattr(choice, "finish_reason", "stop") or "stop",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=model,
            raw=response,
        )
