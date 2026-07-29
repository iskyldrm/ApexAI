# ApexAI — Sub-System C (Task Tracking Dashboard) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or
> superpowers:subagent-driven-development to execute this plan task-by-task.

---

## Context

Sub-Systems A and B produce `agent_runs` and `processes` but the user has
no unified view of "what's happening" across all of them. Sub-System C
provides:

- A **Task** model that wraps a unit of work (user-created or agent-created)
- A **kanban dashboard** with columns: todo / in_progress / review / done / cancelled
- An **activity feed** aggregating events from A + B + manual task changes
- **Notifications** when a task the user owns changes state

ApexAITeam shipped a similar feature with SignalR real-time push. We
port to Next.js + SSE polling (every 5s) for MVP simplicity.

---

## Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Task model | **New `tasks` table** (no reuse of `processes`) | Task is user-facing; process is internal orchestration |
| 2 | Kanban columns | `todo` / `in_progress` / `review` / `done` / `cancelled` | Standard 5-stage flow |
| 3 | Real-time updates | **SSE endpoint + 5s polling fallback** | Lower complexity than WebSocket |
| 4 | Linking | `Task.source` enum: `manual` / `agent_run` / `process` | Track what created each task |
| 5 | Activity feed | **Aggregated from `audit_log` + process_events** | Single source of truth |
| 6 | Notifications | **In-app bell + unread count** | Email/push deferred |
| 7 | Permission | Org-scoped (org_members see org tasks) | Standard RBAC |

---

## DB schema (new tables)

```sql
-- A user/agent-created unit of work
CREATE TABLE tasks (
  id              UUID PRIMARY KEY,
  org_id          UUID,
  user_id         UUID,           -- creator
  assignee_id     UUID,           -- current owner
  title           VARCHAR(255),
  description     TEXT,
  status          VARCHAR(32),    -- todo | in_progress | review | done | cancelled
  priority        VARCHAR(16),    -- low | medium | high | urgent
  source          VARCHAR(32),    -- manual | agent_run | process
  source_id       UUID,           -- FK to agent_runs or processes
  due_at          TIMESTAMP,
  completed_at    TIMESTAMP,
  created_at      TIMESTAMP,
  metadata        JSONB
);

-- Comments / activity entries on a task
CREATE TABLE task_comments (
  id              UUID PRIMARY KEY,
  task_id         UUID REFERENCES tasks(id) ON DELETE CASCADE,
  author_id       UUID,
  author_type     VARCHAR(16),    -- user | agent | system
  body            TEXT,
  created_at      TIMESTAMP
);

-- Per-user notification (the in-app bell)
CREATE TABLE notifications (
  id              UUID PRIMARY KEY,
  user_id         UUID,
  org_id          UUID,
  kind            VARCHAR(64),    -- task.assigned | task.completed | agent.failed | process.paused
  title           VARCHAR(255),
  body            TEXT,
  link            VARCHAR(512),   -- e.g. /tasks/{id}
  read_at         TIMESTAMP,      -- NULL = unread
  created_at      TIMESTAMP
);

-- Indexes
CREATE INDEX ix_tasks_org_status ON tasks(org_id, status);
CREATE INDEX ix_tasks_assignee ON tasks(assignee_id, status);
CREATE INDEX ix_task_comments_task ON task_comments(task_id, created_at);
CREATE INDEX ix_notifications_user_unread ON notifications(user_id, read_at);
```

---

## Phases (20 tasks, ~12-16 hours)

### Phase 1 — Bootstrap (Tasks 1-4)
- `Task`, `TaskComment`, `Notification` SQLModel tables
- Alembic migration
- `TaskSource` enum + status/priority enums

### Phase 2 — Service layer (Tasks 5-9)
- `TaskService.create()`, `update()`, `transition_status()`
- Status transition table (todo → in_progress → review → done; etc.)
- Activity emission (writes to audit_log)
- Linking helpers (link to agent_run / process)

### Phase 3 — REST API (Tasks 10-14)
- `POST /tasks` (create)
- `GET /tasks` (list, filter by status/assignee/org)
- `GET /tasks/{id}` (detail + comments)
- `PATCH /tasks/{id}` (update fields)
- `POST /tasks/{id}/transition` (change status with validation)
- `POST /tasks/{id}/comments` (add comment)
- `GET /notifications` (current user's notifications)
- `POST /notifications/{id}/read` (mark as read)
- `GET /activity-feed` (merged audit_log + process_events)

### Phase 4 — Frontend (Tasks 15-18)
- `/tasks` — kanban board with 5 columns
- `/tasks/[id]` — detail page with comments
- `/notifications` — bell dropdown + page
- `/dashboard` updated with activity feed widget
- Drag-drop status transitions (or button-based)

### Phase 5 — Polish (Tasks 19-20)
- Tests for status transitions, activity aggregation
- SSE endpoint for live updates (`GET /tasks/stream`)
- Final commit

---

## API surface

```
POST   /tasks                       # create
GET    /tasks                       # list (filters: status, assignee, org_id, source)
GET    /tasks/{id}                  # detail + comments
PATCH  /tasks/{id}                  # update title/desc/assignee/priority/due_at
POST   /tasks/{id}/transition       # { "to": "in_progress" }
POST   /tasks/{id}/comments         # { "body": "..." }

GET    /notifications               # current user's
POST   /notifications/{id}/read     # mark read
POST   /notifications/read-all      # mark all read

GET    /activity-feed               # ?org_id=...&limit=50&since=...
GET    /tasks/stream                # SSE for live updates
```

---

## Linking helpers (used by A and B)

```python
# In agent runtime: when a long-running step completes, create a task
await TaskService.create_from_agent_run(
    org_id=run.org_id,
    agent_run_id=run.id,
    title=run.role + ": " + result.summary[:80],
    ...
)

# In workflow executor: same for processes
await TaskService.create_from_process(...)
```

A simple fire-and-forget pattern (no transaction wrapping). If the
task creation fails, log and continue — agent runs shouldn't break.

---

## Status transitions

```
todo ─→ in_progress ─→ review ─→ done
                       ↓
                   cancelled (from any)
```

```python
ALLOWED_TRANSITIONS = {
    "todo": {"in_progress", "cancelled"},
    "in_progress": {"review", "todo", "cancelled"},
    "review": {"in_progress", "done", "cancelled"},
    "done": set(),  # terminal
    "cancelled": {"todo"},  # can re-open
}
```

---

## Open items (deferred)

- Email/push notifications (post-MVP)
- WebSocket real-time push (polling + SSE is enough for MVP)
- Kanban drag-drop on touch devices
- Comments @-mentions / user tagging
- Sub-tasks (nested tasks)