# ApexAI — Task Tracking Hardening Plan (Sub-System C gaps)

> **Closes the ~6 deferred tasks from the original 20-task task-tracking plan.**
> **Depends on:** Sub-System C (already complete), SMTP / SES for email

---

## Context

Sub-System C shipped the core kanban + in-app notifications. Remaining gaps:

1. **Email + push notifications** — operators don't always have the dashboard open
2. **WebSocket real-time updates** — replace 5s polling with push
3. **Sub-tasks** — a task can have nested children
4. **Task dependencies** — "task B blocked on task A"

---

## Phases (10 tasks, ~8-12 hours)

### Phase 1 — Email notifications (Tasks 1-3)
- SMTP config via env: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
- `EmailService.send(user, subject, body)` using `aiosmtplib`
- Trigger on: task.assigned, task.completed, agent.failed
- Templated HTML emails (Jinja2-light: `string.Template`)
- Per-user email preference: `notification_prefs.email` (default true)
- Tests: SMTP mock + template rendering

### Phase 2 — WebSocket live updates (Tasks 4-6)
- `GET /tasks/stream` (WebSocket) — broadcasts task.created / task.updated / task.transitioned
- One channel per org; clients subscribe on login
- Backend uses `broadcaster` library (in-memory pub/sub) or Redis pub/sub for multi-replica
- Frontend: replace 5s polling with `new WebSocket(url + '/tasks/stream')` + handler
- Tests: WebSocket frame emission, multiple subscribers

### Phase 3 — Sub-tasks (Tasks 7-9)
- `tasks.parent_id` FK → `tasks.id` (nullable)
- Tree query: recursive CTE for "all descendants"
- UI: collapsible tree view on /tasks/[id]
- Status: child `done` doesn't auto-complete parent (operator must explicitly do it)
- Tests: parent_id set, cycle prevention (a task can't be its own ancestor)

### Phase 4 — Task dependencies (Task 10)
- `task_dependencies` table: blocker_id, blocked_id
- Status indicator: `blocked_by` count on each task
- A task in `todo` with open dependencies shows blocked badge
- Tests: dependency add / list / prevent cycles

---

## DB additions

```sql
ALTER TABLE tasks ADD COLUMN parent_id UUID REFERENCES tasks(id);

CREATE TABLE task_dependencies (
  blocker_id   UUID REFERENCES tasks(id) ON DELETE CASCADE,
  blocked_id   UUID REFERENCES tasks(id) ON DELETE CASCADE,
  created_at   TIMESTAMP DEFAULT now(),
  PRIMARY KEY (blocker_id, blocked_id),
  CHECK (blocker_id <> blocked_id)
);

CREATE TABLE notification_prefs (
  user_id     UUID PRIMARY KEY,
  email       BOOLEAN DEFAULT true,
  push        BOOLEAN DEFAULT false,
  in_app      BOOLEAN DEFAULT true,
  digest      VARCHAR(16) DEFAULT 'realtime',  -- realtime | daily | weekly | off
);
```

---

## Files

```
backend/app/notifications/
├── __init__.py
├── email.py              # SMTP sender (Task 1-3)
├── websocket.py          # broadcaster / WS endpoint (Task 4-6)
└── prefs.py              # notification_prefs helpers

backend/app/workflow/
├── task_service.py       # +sub-tasks +dependencies (Task 7-10)
└── api/
    └── task_routes.py    # +/stream endpoint

frontend/src/lib/
└── ws.ts                 # WebSocket client
```

---

## WebSocket protocol

```
Client → Server:  (no messages; just subscribe)
Server → Client:
  { "event": "task.created", "task": {...} }
  { "event": "task.updated", "task_id": "...", "changes": {...} }
  { "event": "task.transitioned", "task_id": "...", "from": "todo", "to": "in_progress" }
  { "event": "task.commented", "task_id": "...", "comment": {...} }
```

Channels:
- `org:{org_id}` — all task events for the org
- `user:{user_id}` — direct notifications (task assigned to you, etc.)

---

## Open items

- WebSocket auth: JWT in query param (`?token=...`) since browsers can't set headers on WS
- Email deliverability: SPF/DKIM records on the sending domain
- Push notifications: native APNs/FCM (iOS/Android) — defer to separate plan
- Digest mode: nightly cron to aggregate and email — see Sub-System B hardening plan