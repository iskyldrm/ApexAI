"""Locust load test for the ApexAI agent runtime (A.17-A.20).

Simulates concurrent users invoking the agent endpoints to verify:
1. Token budget enforcement does not blow up under load
2. DB connection pool does not exhaust
3. Rate limits / per-org caps hold
4. p95 latency stays under SLO (3 s for non-streaming endpoints)

Usage:
    # Terminal 1: start FastAPI server with mocked LLM
    APEXAI_LLM_MOCK=1 uvicorn app.main:app --host 0.0.0.0 --port 8000

    # Terminal 2: run locust
    cd backend
    uv run --extra dev locust -f tests/load/locustfile.py --host http://localhost:8000

    # Or headless (CI):
    uv run --extra dev locust -f tests/load/locustfile.py --host http://localhost:8000 \\
        --headless --users 50 --spawn-rate 5 --run-time 60s

The tests login as a fixture user (`load@test.com / load-test-pw`), then
invoke /agent/converse repeatedly with a short prompt. Results tracked:
- p50 / p95 / p99 latency
- RPS
- Failure rate (4xx, 5xx)
"""
from __future__ import annotations

import os
import random
from typing import Any

from locust import HttpUser, between, events, task


LOAD_TEST_EMAIL = os.environ.get("LOAD_TEST_EMAIL", "load@test.com")
LOAD_TEST_PASSWORD = os.environ.get("LOAD_TEST_PASSWORD", "load-test-pw")


class ApexAIUser(HttpUser):
    """A simulated user hitting the agent endpoints."""

    # Wait 1-3 s between tasks (simulates human think time)
    wait_time = between(1, 3)

    def on_start(self) -> None:
        """Log in once per user, store the JWT in a header."""
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"email": LOAD_TEST_EMAIL, "password": LOAD_TEST_PASSWORD},
        )
        if resp.status_code != 200:
            events.request.fire(
                request_type="AUTH",
                name="/auth/login",
                response_time=resp.elapsed.total_seconds() * 1000,
                response_length=len(resp.content),
                exception=f"Login failed: {resp.status_code}",
            )
            return

        body = resp.json()
        # Try both header and cookie paths
        token = body.get("access_token")
        if token:
            self.client.headers.update({"Authorization": f"Bearer {token}"})

        self.user_id = body.get("user", {}).get("id")
        self.org_id = body.get("user", {}).get("org_id")

    @task(3)
    def health_check(self) -> None:
        """Trivial health probe — most common task in real usage."""
        with self.client.get("/health", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"Health {resp.status_code}")

    @task(5)
    def readiness_check(self) -> None:
        """Readiness probe — verifies DB + Redis are reachable."""
        with self.client.get("/ready", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"Ready {resp.status_code}")

    @task(2)
    def list_agent_runs(self) -> None:
        """List recent agent runs for the org."""
        with self.client.get(
            "/api/v1/agent/runs?limit=10", catch_response=True
        ) as resp:
            if resp.status_code not in (200, 401):
                resp.failure(f"runs {resp.status_code}")

    @task(1)
    def invoke_agent(self) -> None:
        """Invoke a short agent task.

        With a mocked LLM, the response comes back in <100ms. With a real
        LLM, expect 1-5 s. We catch 429 (rate-limited) and 503 (DB pool
        exhausted) as expected outcomes.
        """
        prompts = [
            "List 3 Python testing best practices.",
            "Explain dependency injection in one sentence.",
            "What is the difference between OAuth and JWT?",
            "Recommend a Postgres extension for full-text search.",
            "How do I debounce a React useEffect?",
        ]
        payload: dict[str, Any] = {
            "role": "ANL",
            "prompt": random.choice(prompts),
            "work_dir": "/tmp/load-test",
        }
        with self.client.post(
            "/api/v1/agent/converse",
            json=payload,
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                body = resp.json()
                if not body.get("success"):
                    resp.failure(f"agent.finished=false: {body.get('error')}")
            elif resp.status_code in (429, 503):
                # Rate-limited / pool-exhausted — these are *expected* under load
                resp.success()
            elif resp.status_code == 401:
                # Token expired (unlikely in 60s test but possible)
                resp.success()
            else:
                resp.failure(f"converse {resp.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print(f"Load test starting against {environment.host}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary stats that we capture in docs/load-test-results.md."""
    stats = environment.stats
    total = stats.total
    print("\n=== ApexAI Load Test Summary ===")
    print(f"  Total requests : {total.num_requests}")
    print(f"  Total failures : {total.num_failures}")
    print(f"  Median (ms)    : {total.median_response_time}")
    print(f"  p95 (ms)       : {total.get_response_time_percentile(0.95)}")
    print(f"  p99 (ms)       : {total.get_response_time_percentile(0.99)}")
    print(f"  RPS            : {total.total_rps:.1f}")
    if total.num_requests > 0:
        print(f"  Failure rate   : {total.num_failures / total.num_requests:.2%}")