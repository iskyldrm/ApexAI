# ApexAI — Sub-System E (Build/Test Pipeline) Implementation Plan

> **Goal:** run a project's test suite in a fresh, sandboxed container and report results back to the agent / user.
> **Depends on:** Sub-System A (`run_command` tool), Sub-System B (CI integration via workflow triggers)

---

## Context

Today, the `run_tests` tool spawns `pytest` directly on the host machine. This is:
1. **Unsafe** — `pytest` plugins can execute arbitrary code; a malicious test fixture could read env vars
2. **Slow at scale** — installing all deps for every run
3. **No parallelism** — every test runs serially in the same env

Sub-System E wraps each `run_tests` invocation in a fresh Docker container with:
- Read-only mount of the project source
- Cached dependency layer (reuse pip/npm cache between runs)
- Per-test isolation (each test file in its own container)
- Structured JSON output

---

## Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Runtime | **Docker container per run** (matches Sub-System A's existing `run_command` sandboxing direction) | Standard, secure, reproducible |
| 2 | Image | **Per-language base images** (`apexai-test-python:3.12`, `apexai-test-node:22`, `apexai-test-go:1.22`, etc.) | Pre-baked with test runners |
| 3 | Mounts | Read-only source + writable `/tmp` for cache + writable `/workspace/.pytest_cache` etc. | Source can't be mutated |
| 4 | Network | **Default disabled**; opt-in via `network: true` kwarg | Most tests don't need network |
| 5 | Caching | **Docker buildkit cache mounts** for `~/.cache/pip`, `~/.npm`, `~/.cache/go-build` | 10-50x speedup on warm cache |
| 6 | Output | Structured JUnit XML + JSON summary; parsed server-side | Industry standard |
| 7 | Per-test parallelism | **Optional via `pytest -n auto` / `vitest --shard`** | Off by default; user opts in |
| 8 | Result storage | New `test_runs` table with run_id, suite, duration, pass/fail counts, flaky markers | Permanent record |

---

## DB additions

```sql
CREATE TABLE test_runs (
  id            UUID PRIMARY KEY,
  agent_run_id  UUID,                       -- nullable (manual runs)
  process_id    UUID,                       -- nullable (B sub-system)
  project_path  VARCHAR(512),
  language      VARCHAR(16),                -- python | node | go | rust
  framework     VARCHAR(32),                -- pytest | vitest | go test | cargo test
  status        VARCHAR(32),                -- running | passed | failed | errored | timeout
  total         INT,
  passed        INT,
  failed        INT,
  skipped       INT,
  errors        INT,
  duration_ms   INT,
  network       BOOLEAN DEFAULT false,
  image         VARCHAR(128),               -- exact image used (incl. hash)
  started_at    TIMESTAMP,
  finished_at   TIMESTAMP,
  output_path   VARCHAR(512),               -- S3 / local path to full logs
  metadata      JSONB
);

CREATE INDEX ix_test_runs_project ON test_runs(project_path, started_at DESC);
CREATE INDEX ix_test_runs_status ON test_runs(status, started_at DESC);
```

---

## Phases (40 tasks, ~22-30 hours)

### Phase 1 — Image registry (Tasks 1-5)
- `apexai-test-python:3.12` Dockerfile: pytest, coverage, ruff, mypy pre-installed
- `apexai-test-node:22`: vitest, eslint, prettier
- `apexai-test-go:1.22`: go test, golangci-lint
- Build + push to local registry (or use docker hub mirror)
- Versioned tags for reproducibility

### Phase 2 — Container runner (Tasks 6-12)
- `ContainerRunner.run(spec)` → spawns docker, captures stdout, enforces timeout
- `RunSpec`: language, project_path, test_filter, network, timeout_seconds, env_overrides
- Output streaming to file (capped at 50MB)
- Resource limits: CPU, memory, pids
- Auto-cleanup via `docker rm -f`

### Phase 3 — Framework adapters (Tasks 13-19)
- `PythonAdapter`: `pytest -v --tb=short --junitxml=...`
- `NodeAdapter`: `vitest run --reporter=junit`
- `GoAdapter`: `go test -v -json`
- `RustAdapter`: `cargo test -- --format=json`
- Each parses its native format → uniform `TestResult` dict

### Phase 4 — Result storage + persistence (Tasks 20-24)
- `TestRunService.create/update/complete`
- Store results in `test_runs` table
- Surface failures via Sub-System C (auto-create task on test failure)
- Linked back to `agent_run_id` / `process_id`

### Phase 5 — Flakiness detection (Tasks 25-28)
- `FlakinessDetector`: tracks per-test pass/fail across recent runs
- A test passing >0% and <100% of last 10 runs = "flaky"
- Auto-mark flaky tests in UI; exclude from "blocking" status
- Daily job recomputes from `test_runs`

### Phase 6 — Parallel execution (Tasks 29-32)
- `ParallelRunner`: split test list into N shards, run N containers in parallel
- N = env `APEXAI_TEST_PARALLELISM` or per-run override
- Aggregate per-shard results → single TestRun

### Phase 7 — Integration (Tasks 33-40)
- Replace `run_tests` tool's pytest call with `ContainerRunner` when env `APEXAI_TEST_CONTAINER=1`
- REST API: `POST /test-runs` (manual), `GET /test-runs/{id}`, `GET /test-runs?project=...`
- Sub-System B: add CI integration (post-commit hook → run tests → create task on fail)
- Frontend: test runs dashboard with pass/fail trends + flaky test list
- Prometheus: `test_runs_total{status,language}`, `test_run_duration_seconds{language}`

---

## Files

```
backend/app/testing/
├── __init__.py
├── models.py              # TestRun
├── runner.py              # ContainerRunner + RunSpec
├── adapters/
│   ├── __init__.py
│   ├── python.py          # pytest adapter
│   ├── node.py            # vitest adapter
│   ├── go.py              # go test adapter
│   └── rust.py            # cargo test adapter
├── flakiness.py           # per-test pass/fail tracking
├── parallel.py            # sharding
├── service.py             # TestRunService
└── api.py                 # /test-runs/* endpoints

docker/test-images/
├── python.Dockerfile
├── node.Dockerfile
├── go.Dockerfile
└── rust.Dockerfile
```

---

## Container spec

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest pytest-cov pytest-xdist ruff mypy
WORKDIR /workspace
# Source mounted read-only at /workspace
# /workspace/.cache writable for pip cache
# /tmp writable
ENTRYPOINT ["pytest"]
```

---

## Open items

- Container startup overhead (~1-3s); consider pre-warmed pool for hot paths
- Storage of large `output_path` files — S3 / GCS for prod, local for dev
- Windows runners not supported (Docker daemon dependency)
- Resource limits may need tuning per project (some test suites need >4GB RAM)