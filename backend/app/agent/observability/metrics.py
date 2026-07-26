"""Hook AgentLoop results into Prometheus metrics.

Called by AgentLoop at the end of a run to record:
- AGENT_RUNS counter (by role + finish_reason)
- AGENT_RUN_DURATION histogram
- AGENT_TOKENS counter (input + output, per role/model)
- AGENT_STEPS histogram
"""
from app.core.metrics import (
    AGENT_RUNS,
    AGENT_RUN_DURATION,
    AGENT_STEPS,
    AGENT_TOKENS,
)


def record_agent_run(*, role: str, model: str, finish_reason: str, steps: int, duration_seconds: float,
                     input_tokens: int, output_tokens: int) -> None:
    """Emit metrics for a completed agent run. Safe to call when disabled — no-op if so."""
    try:
        AGENT_RUNS.labels(role=role, finish_reason=finish_reason, model=model or "unknown").inc()
        AGENT_RUN_DURATION.labels(role=role).observe(duration_seconds)
        AGENT_STEPS.labels(role=role).observe(steps)
        if input_tokens:
            AGENT_TOKENS.labels(role=role, model=model or "unknown", direction="input").inc(input_tokens)
        if output_tokens:
            AGENT_TOKENS.labels(role=role, model=model or "unknown", direction="output").inc(output_tokens)
    except Exception:
        # Never let metrics break a run
        pass
