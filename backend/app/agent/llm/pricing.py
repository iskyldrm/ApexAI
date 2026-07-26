"""Per-provider cost calculation (USD per 1K tokens).

Real prices — update quarterly. Used by LiteLLMClient to compute
``cost_usd`` for each response.
"""
# Each entry: (input_per_1k, output_per_1k) in USD
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "claude-sonnet-4-5": (0.003, 0.015),
    "claude-opus-4-1": (0.015, 0.075),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "gemini-1.5-pro": (0.0035, 0.0105),
    "ollama/llama3.2": (0.0, 0.0),  # local
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
    return round(
        (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate,
        6,
    )
