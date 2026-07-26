# ApexAI Sub-System A — Agent Runtime (Design Spec)

> Status: **Implemented** (~50/70 plan tasks complete; remaining: production
> hardening, security audit, OpenTelemetry). All 16 tools, 4 safety systems,
> AgentLoop, REST API, frontend page, and observability hooks are in place.

---

## 1. Purpose

Sub-System A is the **agent runtime** that drives role-based specialist agents.
It builds on Sub-System F (auth, RBAC, key vault, audit log) and exposes
a single endpoint that takes a role + task description and produces a result.

Used by:
- **Sub-System B (Workflow)** — runs a multi-step process by chaining
  agent invocations
- **Sub-System G (Frontend)** — user-driven runs from the /agent page
- **External clients** — REST API (`/api/v1/agent/converse`)

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     /api/v1/agent/converse                     │
│  (REST: Pydantic validate → resolve model via settings → run)  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │     AgentLoop.run    │  ← main loop
              │ (runtime.py)         │
              └──────────┬───────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐    ┌────────────┐    ┌─────────────┐
   │ LiteLLM │    │ 4-tier     │    │  16 tools   │
   │ client  │    │ tool call  │    │ (read_file… │
   │(llm/)   │    │ parser     │    │  ask_user)  │
   └─────────┘    └────────────┘    └─────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │  4 safety systems   │
              │  (safety.py)         │
              │  CircuitBreaker      │
              │  RepetitionDetector  │
              │  EditFailureTracker  │
              │  TokenBudgetEnforcer │
              └──────────────────────┘
```

---

## 3. Roles

| Role | Value | Tools | Default model | max_steps |
|---|---|---|---|---|
| MANAGER | MGR | read, list, find, grep, ast_grep, todos, ask_user, run_subagent, finish | gpt-4o | 40 |
| ANALYST | ANL | read-only (no edits) | gpt-4o | 25 |
| DEVELOPER_FE | DEV_FE | full stack (write, edit, run, run_tests, apply_patch) | claude-sonnet-4-5 | 60 |
| DEVELOPER_BE | DEV_BE | full stack | claude-sonnet-4-5 | 60 |
| QA | QA | read + run_command + run_tests (no edits) | gpt-4o | 30 |
| PM | PM | read_file, ask_user, todos | gpt-4o-mini | 15 |
| SUPPORT | SUP | read + run_command | gpt-4o-mini | 25 |

Per-role system prompts are in `app/agent/prompts/__init__.py` and loaded
lazily to avoid circular imports.

---

## 4. Tools (16)

All tools implement the `Tool` dataclass (`app/agent/tools/base.py`) with:
- OpenAI function-call schema (`to_openai_schema()`)
- `is_mutating` flag
- `required_permissions` (e.g. `files:write`, `commands:run`)
- `role_visibility` (defaults to all roles)

| Tool | Type | Sandbox | Key features |
|---|---|---|---|
| `read_file` | read | work_dir containment | UTF-8, line range, size cap |
| `list_dir` | read | work_dir | glob, recursive |
| `find_files` | read | work_dir | path-aware glob (`**/services/*.py`) |
| `grep_search` | read | work_dir | regex, context lines, file globs |
| `ast_grep` | read | work_dir | Python AST structural search |
| `git_status` | read | work_dir | porcelain format |
| `git_diff` | read | work_dir | diff with path filter |
| `list_todos` | read | DB | per-run checklist |
| `ask_user` | read | UI | clarification with optional choices |
| `http_request` | net | URL allowlist + SSRF guard | 100KB cap |
| `write_file` | write | work_dir | 50% reject rule, intentionalFiles |
| `edit_file` | write | work_dir | atomic search-replace, multi-edit |
| `apply_patch` | write | work_dir | multi-file atomic |
| `run_command` | write | work_dir | blocklist, timeout, env overrides |
| `run_tests` | read | work_dir | pytest with structured output |
| `update_todo` | write | DB | checklist create/update |
| `run_subagent` | read | work_dir | recursive, depth ≤ 2 |

(`run_subagent` is `is_mutating=False` but spawns a new agent run, which is
its own DB row — the parent doesn't change state.)

---

## 5. Tool call parsing (4-tier)

`app/agent/tool_parser.py` accepts all the formats different models emit:

1. **Native `tool_calls` field** (OpenAI / Anthropic)
2. **`<tool_call>{...}</tool_call>` XML** (Qwen, Ollama)
3. **` ```json {...} ``` ` blocks**
4. **Balanced-brace extraction** (fallback)

Each tier accepts several field-name conventions: `name`/`tool`/`tool_name`,
`arguments`/`parameters`/`input`/`args`.

---

## 6. Safety systems

All four live in `app/agent/safety.py` and are reset per agent run:

| Guard | Default | Reset on success? |
|---|---|---|
| `CircuitBreaker` | 3 consecutive same-tool fails | yes, per-tool |
| `RepetitionDetector` | 6 read / 12 mutating calls | no |
| `EditFailureTracker` | 5 cumulative edit failures | **no** (force pivot) |
| `TokenBudgetEnforcer` | 500K/run + per-org daily cap | no |

When any guard trips, its `guidance_message()` is injected into the
conversation as a `system` message and the loop exits with
`finish_reason="safety_tripped"` (or `"budget_exceeded"` for tokens).

The `error` field in `AgentResult` carries the guidance text so the UI
can show "Try a different strategy" to the user.

---

## 7. Conversation memory

`app/agent/memory.py` provides:

- `Message` dataclass — in-memory chat message
- `ConversationStore` — async DB-backed append/get on `conversation_messages`
- `trim(messages, max_messages=30)` — keep system + recent
- `maybe_summarize(messages, threshold=50)` — replace oldest with extractive
  summary when over threshold
- `token_aware_trim(messages, max_tokens, role)` — per-role budget
  (MGR/ANL/PM 4K, QA/SUP 8K, DEV 16K)
- `branch(store, parent, child_role)` — child message linked via `parent_id`
- `export_conversation(messages)` — JSON-friendly dump for debugging

Token counting uses tiktoken (`cl100k_base` fallback) so the trim is
model-aware, not character-counting.

---

## 8. Approval gates

`app/agent/gates.py` evaluates tool calls before execution:

- **Migration gate** (Task 30): detects `alembic upgrade`, `prisma migrate`,
  `manage.py migrate`, etc. Pauses the run with
  `status="awaiting_approval"`.
- **Plan approval gate** (Task 31): when `ANL` finishes a plan, requires
  user approval before `DEV` picks up.
- **Permission gate** (Task 15): checks `required_permissions` against the
  user's permissions; platform admins bypass.

Resumption happens via `POST /agent/runs/{id}/resume` with an optional
`{"approval_comment": "..."}` body.

---

## 9. AgentLoop

`app/agent/runtime.py`:

```python
result = await AgentLoop(llm_client, session).run(
    AgentLoopConfig(
        role=Role.DEVELOPER_BE,
        user_prompt="add /agent/usage/summary endpoint",
        work_dir="/Users/me/projects",
        org_id="...",  # for token-usage attribution
        max_steps=60,
    )
)
```

Each iteration:
1. Trim memory (token-aware)
2. Call LLM with full tool schemas
3. Parse tool calls (4-tier)
4. For each call: check gates → execute tool → record success/failure
5. Update safety systems
6. Repeat (or exit on `finish`, max_steps, safety, budget, error)

Returns `AgentResult(success, summary, steps, tokens, finish_reason, intentional_files)`.

---

## 10. REST API

All routes mounted at `/api/v1/agent/`:

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/converse` | user | Run the agent loop (sync) |
| POST | `/converse/stream` | user | SSE event stream |
| GET | `/runs/{id}` | user | Fetch run + messages |
| GET | `/runs/{id}/export` | user | Full conversation as JSON |
| POST | `/runs/{id}/cancel` | user | Cancel a running run |
| POST | `/runs/{id}/resume` | user | Resume from awaiting_approval |
| GET | `/runs` | user | List runs (filter: org_id, role, status) |
| POST | `/admin/cleanup` | platform admin | Mark stuck runs (>1h running) |
| GET | `/admin/stats` | platform admin | Aggregated counts + tokens + cost |
| GET | `/usage/summary?period=7d&org_id=...` | user/admin | Token usage for dashboards |

Token usage is recorded in the `token_usage` table on every LLM call
(via a callback wired into `LiteLLMClient`).

---

## 11. Observability

- **Prometheus** (mounted at `/metrics`):
  - `agent_runs_total{role, finish_reason, model}`
  - `agent_run_duration_seconds{role}` (histogram)
  - `agent_tokens_total{role, model, direction}` (counter)
  - `agent_run_steps{role}` (histogram)
- **Audit log**: every `agent.*` event written to `audit_log` with
  `actor_type="agent"`, `target_type="agent_run"`, `target_id=run_id`.
- **Stuck-run cleanup**: `cleanup_task` background loop runs every 5
  minutes; marks any run with `status='running'` and `started_at < now-1h`
  as `stuck` (Task 55).

---

## 12. Cost cascade hook (Sub-System D — future)

The model resolver (`model_resolver.py`) already implements the override
chain that Sub-System D will populate:
- Request body override (highest priority)
- User-level setting `ai.default_model`
- Org-level setting (with `enforced_by_admin` to block user override)
- Platform-level setting
- RoleConfig default model (built-in fallback)

Sub-System D will insert itself into the LiteLLMClient's `completion()`
call to potentially reroute cheap queries to a smaller model.

---

## 13. Spec coverage

| Spec section | Status |
|---|---|
| Role-based specialists (Tasks 1, 20, 27, 28) | ✅ done |
| Multi-provider model abstraction (6, 38, 52, 53) | ✅ done (LiteLLM wrapper) |
| Conversation memory (3, 23, 40, 41, 42, 43) | ✅ done |
| Tool execution + sandbox (7-15, 51) | ✅ done |
| Code editing (11) | ✅ done |
| Token tracking + cost (6, 19, 38, 61) | ✅ done |
| Safety systems (16, 17, 18, 19) | ✅ done |
| Approval gates (30, 31, 32, 37) | ✅ done |
| SOLUTION.md | ❌ (not used — no follow-up plan in current scope) |
| REST API (33, 34, 35, 36, 37, 39, 55, 57) | ✅ done |
| Observability (25, 47, 48) | ✅ Prometheus + audit. OTel: ⏳ stub |
| Testing (44, 45, 46, 58, 67, 68) | ✅ core. E2E+load: ⏳ |
| Documentation (49, 50, 69, 70) | ✅ this doc + agent-runtime.md. Security audit: ⏳ |

---

## 14. Open items (deferred)

These were intentionally de-scoped to ship the core runtime:

- **OpenTelemetry tracing** (Task 48) — Prometheus is wired, OTel is stubbed
- **Cache layer** (Task 62) — Redis cache for repeat LLM calls
- **Failure recovery** (Task 63) — auto-resume interrupted runs
- **E2E smoke** (Task 58) — testcontainers-based full stack
- **Load test** (Task 68) — Locust script for 50 concurrent runs
- **Security audit** (Task 69) — sandbox escape attempts, RBAC fuzzing
- **PR rejection loop** (Task 32) — wider step limit when fixing review feedback
- **Streaming refactor** (Task 35) — incremental SSE events from inside the loop

These belong to a future hardening pass and don't block B/C/D from
consuming the runtime.
