"""LiteLLM client wrapper with token tracking + cost calculation.

Wraps ``litellm.completion`` so the rest of the agent runtime depends
on a small, mockable surface (``completion() -> LLMResponse``).

Token usage is recorded in a callback so each LLM call can be persisted
to the ``token_usage`` table by the agent loop (F infrastructure).
"""
from __future__ import annotations

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
    """Thin async wrapper around ``litellm.acompletion``."""

    def __init__(self, token_callback: TokenCallback | None = None) -> None:
        self._callback = token_callback

    async def completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a chat completion. Returns an LLMResponse.

        If ``api_key`` is provided, it is passed as ``api_key`` to litellm.
        """
        import litellm

        call_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            call_kwargs["tools"] = tools
        if api_key:
            call_kwargs["api_key"] = api_key
        call_kwargs.update(kwargs)

        try:
            response = await litellm.acompletion(**call_kwargs)
        except Exception as e:
            # Return an error response instead of raising — the agent loop
            # will see finish_reason="error" and decide what to do
            return LLMResponse(
                content=f"LLM error: {e}",
                finish_reason="error",
                model=model,
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
