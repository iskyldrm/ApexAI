# ApexAI — Workflow Orchestration Hardening Plan (Sub-System B gaps)

> **Closes the ~10 deferred tasks from the original 45-task workflow plan.**
> **Depends on:** Sub-System B (already complete), Sub-System C (task creation on fail)

---

## Context

Sub-System B shipped the core DAG executor + queue + DLQ. Remaining gaps:

1. **Parallel step execution** — multiple root steps in the DAG should run concurrently
2. **Cron / scheduled workflows** — "every Monday at 9am, run the reporting workflow"
3. **Visual DAG editor** — drag-drop UI to edit process definitions
4. **Workflow templates** — pre-built templates users can clone

---

## Phases (12 tasks, ~10-14 hours)

### Phase 1 — Parallel step execution (Tasks 1-4)
- Worker: claim multiple ready steps per cycle
- For each step, run as separate asyncio.create_task
- Each task has its own DB session (no shared state)
- Cap at env `APEXAI_WORKFLOW_MAX_PARALLEL` (default 5)
- Tests: process with 3 root steps → all run concurrently

### Phase 2 — Cron scheduling (Tasks 5-7)
- `scheduled_processes` table: process_id, cron_expr, enabled, last_run_at
- APScheduler integration (`apscheduler>=3.10`)
- Triggers `/start` endpoint on schedule
- REST API: `POST /scheduled-processes`, `GET /scheduled-processes`, `DELETE /{id}`
- Tests: schedule fires on time, disabled flag honored

### Phase 3 — Visual DAG editor (Tasks 8-11)
- New `/processes/new` page with `react-flow` (or `@xyflow/react`) for nodes/edges
- Drag nodes, connect with edges, edit prompts inline
- Save: POST /processes with serialized definition
- Optional: load existing process by id for edit mode
- Tests: schema validation on save (no cycles, all names unique)

### Phase 4 — Templates (Task 12)
- `workflow_templates` table: name, category, definition JSON
- Seed: "bug-fix-pipeline", "code-review", "doc-update"
- REST: `GET /workflow-templates`, `POST /workflow-templates/{id}/clone` (creates a draft process)
- Frontend: "Templates" tab in /processes page

---

## DB additions

```sql
CREATE TABLE scheduled_processes (
  id            UUID PRIMARY KEY,
  process_id    UUID REFERENCES processes(id) ON DELETE CASCADE,
  org_id        UUID,
  cron_expr     VARCHAR(64),           -- standard cron (e.g. "0 9 * * 1")
  enabled       BOOLEAN DEFAULT true,
  last_run_at   TIMESTAMP,
  next_run_at   TIMESTAMP,
  created_at    TIMESTAMP DEFAULT now()
);

CREATE INDEX ix_scheduled_processes_next ON scheduled_processes(next_run_at)
  WHERE enabled = true;

CREATE TABLE workflow_templates (
  id            UUID PRIMARY KEY,
  name          VARCHAR(128),
  category      VARCHAR(64),           -- bug-fix | code-review | doc-update | custom
  description   TEXT,
  definition    JSONB,
  created_at    TIMESTAMP DEFAULT now()
);
```

---

## Files

```
backend/app/workflow/
├── parallel.py            # parallel step executor (Task 1-4)
├── scheduler.py           # cron-based scheduled processes (Task 5-7)
├── models.py               # add ScheduledProcess, WorkflowTemplate
└── api/
    ├── scheduled_routes.py
    └── template_routes.py

frontend/src/app/(app)/processes/
├── new/page.tsx            # visual DAG editor (Task 8-11)
└── templates/page.tsx      # template gallery (Task 12)
```

---

## Scheduler architecture

```python
# In FastAPI startup
scheduler.add_job(
    trigger_workflow,
    CronTrigger.from_crontab(schedule.cron_expr),
    args=[schedule.process_id],
    id=f"sched-{schedule.id}",
    replace_existing=True,
)
```

- Use `AsyncIOScheduler` so it doesn't block the event loop
- Restart-survival: serialize schedule state to DB on every change
- Missed runs: if `next_run_at < now()` on startup, fire immediately

---

## Open items

- Parallel execution may burst the LLM rate limit — need per-provider semaphore
- Cron scheduling for hundreds of workflows may need a separate worker process
- Visual editor accessibility (keyboard navigation, screen reader) — defer
- Template marketplace (sharing templates across orgs) — out of scope