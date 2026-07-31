# Load Test Results — Agent Runtime (Sub-System A)

> **Tool:** Locust 2.46.2
> **Target:** ApexAI FastAPI server (3 replicas, 500m–2Gi CPU, 512Mi–2Gi memory)
> **Last run:** 2026-07-31 (template — fill in fresh numbers after each run)

This document captures the load-test methodology, the SLOs we test against,
and the expected outcomes. Re-run before each release; record results below.

---

## Methodology

1. **Deploy target**
   ```bash
   helm upgrade --install apexai deploy/helm/ --values deploy/helm/values.prod.yaml
   kubectl wait --for=condition=ready pod -l app=apex-fastapi --timeout=120s
   ```

2. **Seed load-test user** (once)
   ```bash
   cd backend
   uv run python scripts/create_load_test_user.py
   # creates load@test.com / load-test-pw with org "load-test"
   ```

3. **Run Locust** (headless, 60 s, 50 users, 5 spawn/s)
   ```bash
   cd backend
   uv run --extra dev locust -f tests/load/locustfile.py \
       --host https://apexai-load.example.com \
       --headless --users 50 --spawn-rate 5 --run-time 60s \
       --csv=load-results.csv --html=load-report.html
   ```

4. **Capture results** in the table below.

---

## SLO targets

| Endpoint | p50 | p95 | p99 | Failure rate |
|---|---|---|---|---|
| `GET /health` | < 5 ms | < 20 ms | < 50 ms | < 0.1% |
| `GET /ready` | < 10 ms | < 50 ms | < 100 ms | < 0.1% |
| `GET /api/v1/agent/runs` | < 30 ms | < 150 ms | < 300 ms | < 1% |
| `POST /api/v1/agent/converse` (mocked LLM) | < 200 ms | < 800 ms | < 1.5 s | < 5% |
| `POST /api/v1/agent/converse` (real LLM, Ollama local) | < 2 s | < 5 s | < 10 s | < 5% |

---

## Latest results (template)

> **Run date:** ____-__-__
> **Build:** apexai v0.1.0 — git sha _______
> **Cluster:** 3 replicas · 500m–2Gi CPU · 512Mi–2Gi memory
> **Mocked LLM:** yes (deterministic responses)

| Metric | /health | /ready | /agent/runs | /agent/converse |
|---|---|---|---|---|
| Total requests | ___ | ___ | ___ | ___ |
| Failures | ___ | ___ | ___ | ___ |
| Median (ms) | ___ | ___ | ___ | ___ |
| p95 (ms) | ___ | ___ | ___ | ___ |
| p99 (ms) | ___ | ___ | ___ | ___ |
| RPS | ___ | ___ | ___ | ___ |
| Failure rate | ___% | ___% | ___% | ___% |

---

## Bottlenecks observed

| Run | Bottleneck | Mitigation applied |
|---|---|---|
| v0.0.5 | DB pool exhausted at 80 concurrent users | Bumped `pool_size` 5→10, `max_overflow` 10→20 |
| v0.0.7 | Token callback blocking event loop | Moved callback off the hot path (best-effort, never raises) |
| v0.0.9 | OTel batch processor backlog at 200 RPS | Tuned `BatchSpanProcessor` queue + timeout |

---

## Capacity targets (release gates)

- Sustain **50 concurrent agent invocations** without 5xx errors.
- **p95 < 800 ms** for non-streaming endpoints with mocked LLM.
- **Token budget enforcement** must hold: at 100 concurrent runs × 200K tokens
  per run, no org exceeds its daily cap (default 10M tokens/day).
- **No DB connection exhaustion** — pool size stays under max_overflow
  for the duration of the test.

---

## How to interpret the output

- **p95 > SLO** → investigate token budget / safety system overhead.
- **5xx > 0%** → check the FastAPI logs (`kubectl logs -l app=apex-fastapi`).
  Likely causes: DB pool exhaustion, OTel exporter timeout, LLM provider rate-limit.
- **429 expected** → that's our per-org rate limiter doing its job. The load
  test treats 429 as success.

---

## Future hardening

- **k6 or Gatling** comparison (Locust's threading model is conservative;
  async k6 gives higher RPS for I/O-bound workloads)
- **Long-running test** (1 h soak) to catch slow memory leaks
- **Chaos engineering** integration (kill a pod mid-test, verify resume works)
- **Multi-region** load test (eu + us-east) — see Sub-System E