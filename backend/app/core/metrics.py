"""Prometheus metrics for FastAPI.

Exports Counter/Histogram for HTTP requests AND agent-specific events.
Designed to be enabled only when the ``metrics_enabled`` flag is set so
test runs aren't slow.
"""
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# Total HTTP requests by method, path, and status
HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

# Request latency in seconds
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# ----- Agent metrics (A sub-system) -----

AGENT_RUNS = Counter(
    "agent_runs_total",
    "Total agent runs by role and finish_reason",
    ["role", "finish_reason", "model"],
)

AGENT_RUN_DURATION = Histogram(
    "agent_run_duration_seconds",
    "Agent run wall-clock duration",
    ["role"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

AGENT_TOKENS = Counter(
    "agent_tokens_total",
    "Total tokens consumed by agent runs",
    ["role", "model", "direction"],  # direction: input | output
)

AGENT_STEPS = Histogram(
    "agent_run_steps",
    "Number of LLM steps per agent run",
    ["role"],
    buckets=(1, 2, 5, 10, 20, 40, 80, 160),
)

# ----- Process / workflow metrics (B sub-system) -----

PROCESSES_TOTAL = Counter(
    "processes_total",
    "Total workflows by status",
    ["status"],
)

PROCESS_STEP_DURATION = Histogram(
    "process_step_duration_seconds",
    "Process step wall-clock duration",
    ["role", "status"],
    buckets=(0.5, 1, 5, 10, 30, 60, 120, 300, 600),
)

PROCESS_DLQ_OPEN = Counter(
    "process_dlq_open",
    "Cumulative count of steps that hit DLQ",
    ["role"],
)


def metrics_response() -> tuple[bytes, str]:
    """Render the Prometheus exposition format."""
    return generate_latest(), CONTENT_TYPE_LATEST

