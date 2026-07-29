# ApexAI — Agent Runtime Hardening Plan (Sub-System A gaps)

> **Closes the ~20 deferred tasks from the original 70-task agent-runtime plan.**
> **Depends on:** Sub-System A (already complete), Sub-System F (audit + metrics infra)

---

## Context

Sub-System A's first-pass implementation shipped ~50/70 plan tasks. Remaining gaps fall into 5 buckets:

1. **Distributed tracing** (Task 48) — OpenTelemetry spans per LLM call / tool exec
2. **Redis cache** (Task 62) — dedupe repeat LLM calls by (model + prompt hash)
3. **Failure recovery** (Task 63) — auto-resume crashed `agent_runs` on startup
4. **Security hardening** (Task 69) — sandbox escape attempts + RBAC fuzzing
5. **Load + chaos** (Tasks 68 + E2E) — Locust + testcontainers

---

## Phases (20 tasks, ~14-18 hours)

### Phase 1 — OpenTelemetry tracing (Tasks 1-4)
- `opentelemetry-instrumentation-fastapi` middleware (auto-instrument HTTP)
- Manual spans around: `litellm.acompletion`, `tool.handler`, `safety.check`
- Span attributes: agent_run_id, role, model, tool_name, input/output_tokens, cost_usd
- OTLP exporter (configurable endpoint via `OTEL_EXPORTER_OTLP_ENDPOINT`)
- Tests: span emission + attribute propagation

### Phase 2 — Redis cache (Tasks 5-8)
- Cache key: `apexai:cache:{model}:{sha256(normalized_prompt)}`
- TTL: configurable (default 24h)
- Disabled if `APEXAI_LLM_CACHE_DISABLED=1`
- Cache hit returns prior response verbatim; logs `cache.hit` audit event
- Stored: content, tool_calls, finish_reason, tokens, cost_usd
- Tests: hit / miss / TTL expiry / per-model isolation

### Phase 3 — Failure recovery (Tasks 9-12)
- On FastAPI startup, scan `agent_runs` for `status='running'` AND `started_at < now - 30min`
- Set them to `status='interrupted'`
- Add `POST /agent/runs/{id}/resume` to restart from last checkpoint
- Persist loop checkpoint every N steps (new `agent_run_checkpoints` table)
- Tests: startup recovery + manual resume

### Phase 4 — Security hardening (Tasks 13-16)
- Sandbox escape attempts in CI:
  - path traversal (`../../../../etc/passwd`)
  - command injection (`; rm -rf /`)
  - URL SSRF (private IP ranges, metadata endpoints)
  - prompt injection (tool outputs that try to override system prompt)
- RBAC fuzzing: random org_id / user_id combinations, assert 403
- Output: `docs/security-agent-runtime.md` with findings + mitigations

### Phase 5 — Load testing (Tasks 17-20)
- `locustfile.py` — 50 concurrent `/agent/converse` calls with varying prompts
- Run for 10 minutes, measure p50/p95/p99 latency, throughput, error rate
- Failure modes: LLM rate limit, tool timeout, budget exceeded
- SLO: p95 < 30s, error rate < 1%
- Output: `docs/load-test-results.md`

---

## DB additions

```sql
-- Loop checkpoints for resume
CREATE TABLE agent_run_checkpoints (
  id            UUID PRIMARY KEY,
  agent_run_id  UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
  step_number   INT,
  state         JSONB,                   -- messages snapshot
  created_at    TIMESTAMP DEFAULT now()
);

-- Cache metadata (the values themselves live in Redis)
CREATE TABLE llm_cache_entries (
  cache_key     VARCHAR(128) PRIMARY KEY,
  model         VARCHAR(128),
  hit_count     INT DEFAULT 0,
  cost_saved    FLOAT DEFAULT 0,
  expires_at    TIMESTAMP,
  created_at    TIMESTAMP DEFAULT now()
);
```

---

## Files

```
backend/app/agent/
├── observability/
│   └── tracing.py         # OTel spans (Task 1-4)
├── cache.py               # Redis-backed LLM cache (Task 5-8)
├── recovery.py            # startup recovery + resume (Task 9-12)
└── security/              # sandbox escape tests (Task 13-16)

backend/tests/agent/
├── test_tracing.py
├── test_cache.py
├── test_recovery.py
└── test_security.py       # path traversal, SSRF, RBAC fuzz

backend/tests/load/
└── locustfile.py          # 50-concurrent load test

docs/
├── security-agent-runtime.md
└── load-test-results.md
```

---

## OTel span hierarchy

```
HTTP POST /agent/converse           (fastapi auto-instrument)
  └─ agent.run                       role=DEV_BE, agent_run_id=...
      ├─ llm.completion              model=gpt-4o, tokens_in=800, tokens_out=200, cost=$0.01
      ├─ tool.execute                 tool=read_file, ok=true
      ├─ llm.completion
      └─ agent.finish                 finish_reason=finished
```

---

## Open items

- OTel adds 5-10ms overhead per span — disable in tests via `OTEL_DISABLED=true`
- Redis cache invalidation is manual (no automatic re-validation when model version changes)
- Failure recovery may double-charge for crashed runs; add idempotency keys to LiteLLM calls
- Security audit should be re-run after every dependency upgrade