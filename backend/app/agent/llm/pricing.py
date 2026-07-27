"""Per-provider cost calculation (USD per 1K tokens).

Real prices — update quarterly. Used by LiteLLMClient to compute
``cost_usd`` for each response.

Local Ollama + the MiniMax gateway default to $0 since we don't have
an authoritative price list for them. Override in production by
setting ``APEXAI_MODEL_INPUT_PRICE`` and ``APEXAI_MODEL_OUTPUT_PRICE``
(micro-USD per 1K tokens) in env.
"""
import os


_DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "claude-sonnet-4-5": (0.003, 0.015),
    "claude-opus-4-1": (0.015, 0.075),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "gemini-1.5-pro": (0.0035, 0.0105),
    "MiniMax-M3": (0.0, 0.0),  # MiniMax has no public pricing yet
    "llama3.2": (0.0, 0.0),     # local Ollama
    "ollama/llama3.2": (0.0, 0.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    # Strip any provider prefix for lookup
    bare = model.split("/", 1)[-1] if "/" in model else model
    in_rate, out_rate = _DEFAULT_PRICING.get(bare, (0.0, 0.0))
    # Allow env override
    env_in = os.environ.get("APEXAI_MODEL_INPUT_PRICE")
    env_out = os.environ.get("APEXAI_MODEL_OUTPUT_PRICE")
    if env_in and env_out:
        in_rate = float(env_in) / 1_000_000  # micro-USD → USD
        out_rate = float(env_out) / 1_000_000
    return round(
        (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate,
        6,
    )
