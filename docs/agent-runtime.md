# Agent Runtime

The ApexAI Agent Runtime is a role-based specialist execution engine.
Each run is driven by a single LLM but constrained to a role's tools,
permissions, and step budget, with four safety guards watching for
loops, runaway edits, and budget exhaustion.

## Quick start

```bash
# 1. Login
TOKEN=$(curl -X POST localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@apex.ai","password":"admin123"}' \
  -c cookies.txt | jq -r '.access_token')

# 2. Run a developer agent
curl -X POST localhost:8000/api/v1/agent/converse \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "role": "DEV_BE",
    "prompt": "Add a /usage/summary endpoint to app/agent/api/routes.py",
    "work_dir": "/Users/me/projects"
  }' | jq .
```

## Roles

| Role | Best for | Allowed tools |
|---|---|---|
| `ANL` | Read-only analysis | read_file, list_dir, find_files, grep_search, ast_grep, git_*, todos, ask_user |
| `DEV_BE` | Backend coding | full toolset including write_file, edit_file, apply_patch, run_command, run_tests |
| `DEV_FE` | Frontend coding | same as DEV_BE |
| `QA` | Verify build/tests | read tools + run_command + run_tests (no edits) |
| `MGR` | Orchestrate | read + run_subagent (delegates work) |
| `PM` | Specs/stories | read_file + ask_user + todos |
| `SUP` | Read-only investigation | read tools + run_command |

## Configuration

Override the default model per-org or per-user via the `settings` table:

```sql
-- Org-level default
INSERT INTO settings (scope, scope_id, key, value, enforced_by_admin)
VALUES ('org', '<org-uuid>', 'ai.default_model', '{"model": "gpt-4o"}', true);

-- User override (ignored if org has enforced_by_admin=true)
INSERT INTO settings (scope, scope_id, key, value, enforced_by_admin)
VALUES ('user', '<user-uuid>', 'ai.default_model', '{"model": "claude-opus-4-1"}', false);

-- Per-org daily token cap
INSERT INTO settings (scope, scope_id, key, value, enforced_by_admin)
VALUES ('org', '<org-uuid>', 'ai.daily_token_budget', '{"tokens": 1000000}', false);
```

## Safety: what stops a runaway run

1. **Circuit breaker** — same tool fails 3 times in a row → guidance inject
2. **Repetition detector** — same call (tool+args) 7 times → guidance
3. **Edit failure tracker** — 5 cumulative edit failures (write/edit/patch)
4. **Token budget** — per-run 500K tokens OR per-org daily cap

When any guard trips, the loop exits with `finish_reason`:
- `safety_tripped`
- `budget_exceeded`
- `max_steps` (loop hit the step cap cleanly)
- `finished` (LLM called `finish` tool)
- `error` (unhandled exception)

## Approval gates

The runtime pauses runs that touch schema migrations:

```
> run_command: alembic upgrade head
⚠️ Schema migration detected. Run paused.
> POST /agent/runs/{id}/resume  {"approval_comment": "approved"}
```

Same flow for plan handoffs from ANL → DEV.

## API surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/agent/converse` | Run synchronously |
| `POST` | `/api/v1/agent/converse/stream` | SSE event stream |
| `GET` | `/api/v1/agent/runs/{id}` | Run + messages |
| `GET` | `/api/v1/agent/runs/{id}/export` | Full conversation JSON |
| `POST` | `/api/v1/agent/runs/{id}/cancel` | Cancel a running run |
| `POST` | `/api/v1/agent/runs/{id}/resume` | Resume from approval gate |
| `GET` | `/api/v1/agent/runs` | List runs (org/role/status filters) |
| `GET` | `/api/v1/agent/usage/summary?period=7d` | Token usage + cost |
| `POST` | `/api/v1/agent/admin/cleanup` | Mark stuck runs |
| `GET` | `/api/v1/agent/admin/stats` | Aggregated counts |

## Metrics

Available at `/metrics` (Prometheus):

```
agent_runs_total{role="DEV_BE",finish_reason="finished",model="claude-sonnet-4-5"} 142
agent_run_duration_seconds_bucket{role="DEV_BE",le="10.0"} 89
agent_tokens_total{role="DEV_BE",model="claude-sonnet-4-5",direction="input"} 1.2M
```

## How the loop runs

```
while steps < max_steps:
    messages = trim(messages)
    response = await llm.completion(messages, tools)
    budget.record(response.tokens)
    tool_calls = parse_tool_calls(response)

    for tc in tool_calls:
        if tc.name == "finish": break  # special marker, don't execute
        gate = evaluate_gates(tc)
        if gate.trip: pause run, return  # resume later
        result = await tools[tc.name].handler(ctx, tc.arguments)
        record(tool, success/failure)
        messages.append(tool_result_message)

    check_safety_guards()
    check_token_budget()
```

## Adding a new tool

```python
# app/agent/tools/my_tool.py
from app.agent.tools.base import Tool, ToolContext, ToolResult

class MyTool(Tool):
    def __init__(self):
        super().__init__(
            name="my_tool",
            description="What it does",
            parameters_schema={"type": "object", "properties": {...}, "required": [...]},
            handler=self._run,
            is_mutating=False,
            required_permissions=(),  # or ("files:write",)
        )
    async def _run(self, ctx, args):
        # ... your logic ...
        return ToolResult(ok=True, output="done")

# app/agent/tools/__init__.py — add to _DEFAULT_TOOLS
```

Tests go in `tests/agent/test_my_tool.py` following the same TDD pattern
as the existing 16 tool test files.

## Limitations & open items

- Streaming is fire-and-forget (the SSE endpoint runs the whole loop, then
  streams the result). True incremental streaming is on the roadmap.
- No E2E testcontainers test yet (Task 58) — currently mocked LLM.
- OpenTelemetry tracing is stubbed (Task 48) — only Prometheus is wired.
- No Redis cache for repeat LLM calls (Task 62).
- No auto-resume of crashed runs (Task 63).
- Security audit (Task 69) and load test (Task 68) not yet performed.

See `docs/superpowers/specs/2026-07-25-agent-runtime-design.md` for the
full design spec and roadmap.
