"""Prometheus metrics for FastAPI.

Exports Counter/Histogram for HTTP requests. Designed to be enabled only
when the OTEL_PROM_ENABLED flag is set so test runs aren't slow.
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


def metrics_response() -> tuple[bytes, str]:
    """Render the Prometheus exposition format."""
    return generate_latest(), CONTENT_TYPE_LATEST
