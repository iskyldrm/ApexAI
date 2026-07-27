# ApexAI — Sub-System B (Workflow Orchestration) Implementation Plan

> **Tech stack:** Python 3.12, FastAPI (from F), SQLAlchemy async, PostgreSQL `SELECT FOR UPDATE SKIP LOCKED`, Tenacity, Pydantic v2
> **Depends on:** Sub-System A (AgentLoop) — B's worker calls `/api/v1/agent/converse` per step
> **Estimated tasks:** ~45 across 6 phases

---

## Context

Sub-System A exposes `POST /api/v1/agent/converse` for a single LLM-driven
agent run. But real workflows are multi-step: **analyze the repo →
dev implements → QA verifies → manager reports**. Each step is an
agent invocation, and they hand off artifacts between each other.

Sub-System B provides that orchestration:
- Define a workflow as a **DAG of steps** (each step = a role + prompt)
- Run it on a **Postgres-backed queue** (SKIP LOCKED, no external service)
- Track every state change in an **event-sourced log** (ProcessEvent)
- Handle **retries with exponential backoff** + dead-letter queue
- Expose **REST API + dashboard** for process lifecycle

ApexAITeam proved this pattern in C#/MongoDB; we port the proven shape
to Python/Postgres.

---

## Decisions (locked)

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Execution model | **DAG of steps** | Production-flexible; resume per step; supports parallel branches |
| 2 | Queue | **Postgres SELECT FOR UPDATE SKIP LOCKED** | No extra service, transactional, scales to N workers |
| 3 | Retry | **Exponential backoff (1, 4, 16, 64, 256s) → DLQ after 5** | Industry standard; DLQ gives replay + alerts |
| 4 | State model | **Event-sourced via ProcessEvent** | Full audit trail, easy debugging, replayable |
| 5 | Worker model | **Async background tasks per FastAPI process** | Stateless; horizontal scale = more replicas |
| 6 | Workflow definition | **JSON in `processes.definition` column** | No DSL needed; UI can edit directly |
| 7 | Step hand-off | **Output of step N → input of step N+1 via templating** | `{{steps.analyze.output}}` syntax |
| 8 | Cancellation | **Soft cancel (status='cancelled')** | Lets workers exit cleanly |
| 9 | Failure isolation | **One step failure doesn't kill siblings** | DAG semantics |

---

## DB schema (new tables)

```sql
-- A multi-step workflow definition
CREATE TABLE processes (
  id              UUID PRIMARY KEY,
  org_id          UUID,
  user_id         UUID,
  name            VARCHAR(255),
  definition      JSONB,    -- DAG: {steps: [...], edges: [...]}
  status          VARCHAR(32),  -- draft | queued | running | paused | completed | failed | cancelled
  current_step    VARCHAR(64),  -- name of step currently executing
  created_at      TIMESTAMP,
  started_at      TIMESTAMP,
  finished_at     TIMESTAMP,
  metadata        JSONB
);

-- One row per step execution (a node in the DAG)
CREATE TABLE process_steps (
  id              UUID PRIMARY KEY,
  process_id      UUID REFERENCES processes(id) ON DELETE CASCADE,
  step_name       VARCHAR(64),  -- unique within process
  role            VARCHAR(16),  -- agent role (MGR, DEV_BE, ...)
  status          VARCHAR(32),  -- pending | queued | running | completed | failed | skipped | cancelled
  attempt         INTEGER DEFAULT 0,
  max_attempts    INTEGER DEFAULT 5,
  inputs          JSONB,        -- resolved inputs (from upstream step outputs + params)
  outputs         JSONB,        -- final outputs (last attempt)
  agent_run_id    UUID,         -- FK to agent_runs (sub-system A)
  started_at      TIMESTAMP,
  finished_at     TIMESTAMP,
  error           TEXT,
  next_retry_at   TIMESTAMP,    -- for exponential backoff
  metadata        JSONB
);

-- Append-only event log (event sourcing)
CREATE TABLE process_events (
  id              BIGSERIAL PRIMARY KEY,
  process_id      UUID REFERENCES processes(id) ON DELETE CASCADE,
  step_id         UUID REFERENCES process_steps(id) ON DELETE CASCADE,
  event_type      VARCHAR(64),  -- process.created | step.queued | step.started | step.completed | step.failed | process.completed | ...
  payload         JSONB,
  actor_id        VARCHAR(64),  -- user or "system"
  created_at      TIMESTAMP DEFAULT now()
);

-- Dead-letter queue
CREATE TABLE process_dlq (
  id              UUID PRIMARY KEY,
  process_id      UUID,
  step_id         UUID,
  payload         JSONB,
  reason          TEXT,
  retry_count     INTEGER,
  failed_at       TIMESTAMP,
  resolved_at     TIMESTAMP,    -- when ops replays
  resolution      TEXT          -- "replayed" | "abandoned" | "fixed"
);

-- Indexes
CREATE INDEX ix_process_steps_process ON process_steps(process_id);
CREATE INDEX ix_process_steps_status  ON process_steps(status, next_retry_at);
CREATE INDEX ix_process_events_proc    ON process_events(process_id, id);
CREATE INDEX ix_process_dlq_open       ON process_dlq(resolved_at) WHERE resolved_at IS NULL;
```

---

## Phases

### Phase 1 — Bootstrap (Tasks 1-7)
- DB models: `Process`, `ProcessStep`, `ProcessEvent`, `ProcessDLQ`
- Alembic migration
- `ProcessDefinition` Pydantic model (DAG validator)
- Step template resolver (`{{steps.X.output}}` substitution)
- Cycle detection in DAG
- Repository pattern (`ProcessRepository`)

### Phase 2 — Queue + Worker (Tasks 8-14)
- `claim_next_steps()` using `SELECT FOR UPDATE SKIP LOCKED`
- `enqueue_step()`, `mark_step_running()`, `mark_step_completed()`, `mark_step_failed()`
- Exponential backoff schedule helper
- DLQ on `attempt >= max_attempts`
- Background `worker_loop()` (asyncio task)
- Graceful shutdown on signal

### Phase 3 — State machine + event sourcing (Tasks 15-22)
- `ProcessStateMachine` with allowed transitions
- `emit_event()` writes ProcessEvent
- Process status transitions: draft → queued → running → (completed | failed | paused | cancelled)
- Step status transitions: pending → queued → running → (completed | failed | retrying | skipped)
- Aggregate rebuild from events (for audit / debugging)
- `replay_process()` for DLQ recovery

### Phase 4 — Agent integration (Tasks 23-28)
- `StepExecutor` calls `POST /api/v1/agent/converse` (or `AgentLoop` directly in-process)
- Pass templated inputs to the LLM prompt
- Capture outputs (summary, intentional_files, finish_reason)
- Handle `awaiting_approval` → set process status to `paused`
- Resume via `POST /api/v1/processes/{id}/resume` re-queues the paused step

### Phase 5 — REST API (Tasks 29-34)
- `POST /api/v1/processes` — create a workflow
- `GET  /api/v1/processes/{id}` — fetch + steps + events
- `POST /api/v1/processes/{id}/start` — enqueue
- `POST /api/v1/processes/{id}/cancel`
- `POST /api/v1/processes/{id}/resume`
- `GET  /api/v1/processes` — list with filters

### Phase 6 — Frontend + observability (Tasks 35-40)
- `frontend/src/app/(app)/processes/page.tsx` — list + DAG viewer
- `frontend/src/app/(app)/processes/[id]/page.tsx` — detail + event log
- Prometheus: `processes_total{status}`, `process_step_duration_seconds{role}`, `process_dlq_open`
- Stuck-process cleanup (running > 24h → marked stuck)
- Health check endpoint

---

## API surface

```
POST   /api/v1/processes                       # create
GET    /api/v1/processes                       # list
GET    /api/v1/processes/{id}                  # detail + steps + events
POST   /api/v1/processes/{id}/start            # enqueue
POST   /api/v1/processes/{id}/cancel           # soft cancel
POST   /api/v1/processes/{id}/resume           # re-queue paused steps
GET    /api/v1/processes/{id}/events           # paginated event log
GET    /api/v1/process-dlq                     # list DLQ
POST   /api/v1/process-dlq/{id}/replay         # retry from DLQ
```

---

## Worker loop

```
async def worker_loop(stop_event):
    while not stop_event.is_set():
        async with session.begin():
            steps = await claim_next_steps(session, limit=10)
            for step in steps:
                # Run in background asyncio task so worker can claim more
                asyncio.create_task(execute_step(step))

        await asyncio.sleep(1)  # short poll, SKIP LOCKED handles the rest


async def execute_step(step):
    try:
        step.status = "running"
        step.attempt += 1
        await emit_event(step, "step.started")
        result = await run_agent_for_step(step)  # calls AgentLoop
        step.outputs = result.summary
        step.agent_run_id = result.agent_run_id
        step.status = "completed"
        await emit_event(step, "step.completed")
    except Exception as e:
        step.error = str(e)
        if step.attempt < step.max_attempts:
            step.status = "pending"  # will be re-queued
            step.next_retry_at = utcnow() + backoff(step.attempt)
        else:
            step.status = "failed"
            await dlq_step(step)
        await emit_event(step, "step.failed")
```

---

## Definition example

```json
{
  "name": "Bug fix pipeline",
  "steps": [
    {"name": "analyze", "role": "ANL", "prompt": "Find the root cause of {{input.bug_id}}"},
    {"name": "implement", "role": "DEV_BE", "prompt": "Fix the bug:\n\n{{steps.analyze.outputs.summary}}"},
    {"name": "test", "role": "QA", "prompt": "Run tests after this fix:\n\n{{steps.implement.outputs.summary}}"}
  ],
  "edges": [
    {"from": "analyze", "to": "implement"},
    {"from": "implement", "to": "test"}
  ]
}
```

When all roots are completed, the process is marked `completed`.

---

## Open items (deferred)

- Parallel step execution (multiple roots in the DAG) — Phase 2 covers
  the queue primitives, but the worker picks one root at a time. Will
  scale this with concurrent claims in a later pass.
- Cron-like schedules (every Monday at 9am) — not in scope; workflows
  are always triggered manually or by the API.
- Visual DAG editor (drag-drop in the frontend) — out of scope; users
  edit the JSON directly in Phase 6.

---

## Estimated effort

~45 tasks × ~15-25min/task = 12-18 hours (1 engineer, subagent-driven)
