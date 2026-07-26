"""Prometheus metrics endpoint smoke test."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Hit a non-metrics endpoint first to populate counters
        r = await client.get("/health")
        assert r.status_code == 200
        r = await client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "http_requests_total" in r.text
    assert "http_request_duration_seconds" in r.text
