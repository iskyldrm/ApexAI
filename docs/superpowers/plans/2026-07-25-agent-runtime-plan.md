# ApexAI — Sub-System A (Agent Runtime) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Plan dosyası kapsamı:** Bu plan, F (Multi-tenant Platform) spec/plan'ı üzerine inşa edilen **Sub-System A: Agent Runtime** için spec + implementation plan birleşik dokümanıdır. A'dan sonra B, C, D, E, G ayrı plan dosyalarında ele alınacak.

**Hedef:** F'in `api_keys` + Vault + RBAC + `token_usage` tablolarını kullanarak, **role-based multi-specialist bir agent runtime** kurmak. Bu runtime, tüm AI API protokollerini (OpenAI/Anthropic/Ollama/custom) destekler, tool'ları sandbox'ta çalıştırır, konuşma geçmişini yönetir, token kullanımını F'e yazar.

**Mimari yaklaşım:** Tek Python süreci, içinde **role-based specialists** (MGR, ANL, DEV-FE, DEV-BE, QA, vb.) — her role kendi system prompt + tool set'i + model tercihi ile çalışır. ApexAITeam'ın kanıtlanmış `SELECT FOR UPDATE SKIP LOCKED` queue + `ProcessEvent` event-sourcing pattern'i B sub-system'inde kullanılacak; bu plan sadece agent loop'un kendisini kurar.

**Tech Stack:** Python 3.12, FastAPI (zaten F'te kuruluyor), LiteLLM (multi-provider abstraction), Tenacity (retry), tiktoken + anthropic-tokenizer (token counting), RestrictedPython + subprocess (tool sandbox), PostgreSQL JSONB (conversation storage).

**Repo:** `https://github.com/iskyldrm/ApexAI.git` (branch: `main`)

---

## Context — Neden Bu Plan?

**Sorun:** ApexAITeam ASP.NET Core + MongoDB + Redis üzerinde çalışan tek-tenant bir "AI agent takımı" prototipidir. Çalışıyor, fakat:
- Multi-tenant değil (tek şirket, tek kullanıcı)
- Dili ve stack'i Python'a taşımak istiyoruz
- Tüm alt-sistemlerin iskeleti olan F (Multi-tenant Platform) artık hazır ve 85 task'lık implementasyon planı onaylandı
- A-G'nin diğer 6 alt-sistemi henüz spec düzeyinde outline — bu plan A'yı detaylandırıyor

**Bu plan ne yapacak:**
1. A'nın tüm açık mimari kararlarını netleştirir (multi-agent vs single, model abstraction, conversation storage, tool sandbox)
2. ApexAITeam'den 6 kanıtlanmış pattern'i Python/FastAPI'a port eder (4-tier tool call parsing, conversation trimming, intentionalFiles, circuit breaker, repetition detector, ProcessEvent log)
3. F'in tablolarını (`api_keys`, `token_usage`, `audit_log`) tüketir
4. 7 fazda toplam ~70 bite-sized task ile test edilebilir, çalıştırılabilir bir agent runtime ortaya çıkarır

**Beklenen sonuç:** `POST /api/v1/agent/converse` endpoint'i, role + task description alıp, agent loop'u çalıştırıp, sonucu + token kullanımını DB'ye yazar. Bu endpoint B (Workflow) tarafından tetiklenecek.

---

## F'den Gelen Bağımlılıklar

Bu plan **F'in tamamlanmış olmasını varsayar**. Gerekli F çıktıları:
- `backend/app/` — FastAPI skeleton, deps, config
- `backend/app/models/api_key.py`, `token_usage.py`, `audit_log.py`
- `backend/app/core/security.py` — JWT auth
- `backend/app/core/vault.py` — HashiCorp Vault client
- `backend/app/deps.py` — `get_db`, `get_current_user`
- `backend/app/enums.py` — `Permission`, `Role`, `SettingScope`
- PostgreSQL çalışıyor, `alembic upgrade head` başarılı
- HashiCorp Vault dev modda ayakta
- `audit()` helper

**Yeni F tabloları (A için eklenir):**
- `conversations` — conversation metadata (task_id, role, status, token summary)
- `conversation_messages` — mesajlar (role, content, tool_calls JSONB, tool_result, timestamp)
- `agent_runs` — her agent invocation kaydı (parent_run_id, role, model, start/end, status)

---

## ApexAITeam'den Port Edilecek Pattern'ler

| Pattern | Kaynak | Yeni Yeri |
|---|---|---|
| Multi-turn tool-use loop | `backend/Services/AgentRuntime.cs:RunAgentLoop` | `backend/app/agent/runtime.py:AgentLoop.run()` |
| 4-tier tool call parsing fallback | `ToolExecutor.cs:ParseToolCalls` | `backend/app/agent/tool_parser.py:parse_tool_calls()` |
| Conversation trimming | `AgentRuntime.cs:TrimConversationHistory` | `backend/app/agent/memory.py:trim()` |
| Circuit breaker (3× same tool fail) | `AgentRuntime.cs:MaxConsecutiveToolErrors` | `backend/app/agent/safety.py:CircuitBreaker` |
| Repetition detector (6× same tool) | `AgentRuntime.cs:MaxConsecutiveSameToolCalls` | `backend/app/agent/safety.py:RepetitionDetector` |
| Edit tool total failure tracker | `AgentRuntime.cs:editToolTotalFailures` | `backend/app/agent/safety.py:EditFailureTracker` |
| `intentionalFiles` allow-list | `ToolExecutor.cs:intentionalFiles` | `backend/app/agent/tools/write_file.py` |
| Per-role tool schema filtering | `ToolExecutor.cs:GetToolSchemas(role)` | `backend/app/agent/registry.py:get_tools_for_role()` |
| SOLUTION.md generation | `WorkspaceManager.cs:GenerateSolutionMd` | `backend/app/agent/analysis/solution_md.py` |
| Sub-agent runner | `AgentRuntime.cs:SubAgentRunner` | `backend/app/agent/tools/run_subagent.py` |
| Migration approval gate | `AgentRuntime.cs:WaitForMigrationApproval` | `backend/app/agent/gates.py:MigrationGate` |

**Anti-pattern'ler (YAPMA):**
- ❌ MongoDB + Postgres dual-write → sadece Postgres
- ❌ Redis pub/sub orchestrator → B sub-system'inde Postgres SKIP LOCKED
- ❌ Hard-coded localhost/keys → config + Vault
- ❌ 1000+ satır mega-dosyalar → her dosya 200-400 satır
- ❌ Empty placeholder dizinler → sadece gerekli dosyalar

---

## Mimari Kararlar (Bu Planda Kilitlenen)

| # | Karar | Seçim | Neden |
|---|---|---|---|
| 1 | Agent tipi | **Role-based specialists, tek runtime içinde** | Multi-process overhead'i yok, role'ler kolay test edilir, F'in RBAC'i ile entegre |
| 2 | Model protokol abstraction | **LiteLLM** | OpenAI/Anthropic/Google/Ollama uniform, streaming + tool calling + usage tracking built-in, custom provider desteği |
| 3 | Conversation storage | **PostgreSQL JSONB (`conversation_messages`)** | F'in audit pattern'iyle aynı, RLS, retention kolay, ek operasyonel yük yok |
| 4 | Tool execution sandbox | **Subprocess + RestrictedPython + chroot + resource limits** | K8s pod içinde container'a gerek yok, hızlı, test edilebilir |
| 5 | Code editing yöntemi | **Search-replace blocks (Aider-style) primary, full-file replace for new files** | Modeller arası en güvenilir format; ApexAITeam'ın 50% reject kuralı |
| 6 | Token tracking | **LiteLLM callback → `token_usage` INSERT** | Otomatik, her call'da |
| 7 | Token budget | **Per-agent-run limit + per-org daily cap** | Cost cascade (D) için temiz foundation |
| 8 | Conversation memory | **Sliding window (30 msgs) + summary injection when > N** | ApexAITeam kanıtlanmış pattern; production'da semantik summarization eklenebilir |
| 9 | Approval gates | **Migration approval, tool permissions, role-level gates** | Güvenlik + UX, ApexAITeam pattern'i |
| 10 | Agent API | **Sync (`POST /agent/converse`) + Stream (`POST /agent/converse/stream` SSE)** | B workflow sync kullanır, IDE (Auto Mode C.x) stream ister |

---

## Dosya Yapısı (F üstüne eklenecek)

```
apexai/backend/app/agent/
├── __init__.py
├── runtime.py                 # Ana AgentLoop class (RunAgentLoop benzeri)
├── roles.py                   # Role enum + per-role config (system prompt, tool set, model default)
├── registry.py                # Tool registry (Tool dataclass, register, get_tools_for_role)
├── tool_parser.py             # 4-tier tool call parsing (regex → md JSON → balanced JSON → field extract)
├── memory.py                  # Conversation memory (ConversationStore, trim, summarize)
├── safety.py                  # CircuitBreaker, RepetitionDetector, EditFailureTracker
├── gates.py                   # MigrationGate, ToolPermissionGate, RoleGate
├── analysis/
│   ├── __init__.py
│   └── solution_md.py         # SOLUTION.md generation
├── observability/
│   ├── __init__.py
│   └── activity_log.py        # Per-step activity log (LogActivity benzeri)
├── llm/
│   ├── __init__.py
│   ├── litellm_client.py      # LiteLLM wrapper (token tracking callback bağlı)
│   └── providers.py           # Provider-specific config (openai/anthropic/ollama/custom)
├── tools/
│   ├── __init__.py
│   ├── base.py                # BaseTool, ToolResult, ToolContext dataclasses
│   ├── read_file.py
│   ├── list_dir.py
│   ├── grep_search.py
│   ├── ast_grep.py
│   ├── write_file.py          # intentionalFiles allow-list + 50% reject
│   ├── edit_file.py           # search-replace engine (Aider-style)
│   ├── run_command.py         # subprocess + resource limits
│   ├── git_status.py
│   ├── git_diff.py
│   ├── semantic_search.py     # (Phase 7 — pgvector hazır olunca)
│   └── run_subagent.py        # recursive agent runner
└── api/
    ├── __init__.py
    └── routes.py              # POST /agent/converse, /agent/converse/stream

apexai/backend/alembic/versions/
└── xxxx_add_agent_tables.py   # conversations, conversation_messages, agent_runs

apexai/backend/tests/agent/
├── test_runtime.py
├── test_tool_parser.py
├── test_memory.py
├── test_safety.py
├── test_registry.py
├── test_write_file.py
├── test_edit_file.py
├── test_run_command.py
└── test_solution_md.py

apexai/docs/superpowers/
├── specs/
│   └── 2026-07-25-agent-runtime-design.md  ← Bu plan tamamlandığında
└── plans/
    └── 2026-07-25-agent-runtime-plan.md   ← Bu plan
```

---

## Fazlar ve Task'lar (Toplam ~70 task)

### Faz 1 — Bootstrap (Tasks 1-6)

#### Task 1: Agent package skeleton
**Files:**
- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/roles.py`
- Test: `backend/tests/agent/__init__.py`

- [ ] **Step 1:** `pyproject.toml`'a `litellm>=1.50`, `tenacity>=9.0`, `tiktoken>=0.8`, `anthropic-tokenizer>=0.1`, `restrictedpython>=7.4` ekle
- [ ] **Step 2:** `uv sync` çalıştır
- [ ] **Step 3:** `backend/tests/agent/test_roles.py` yaz — `Role` enum + per-role config testleri
- [ ] **Step 4:** Test fail olduğunu doğrula: `cd backend && uv run pytest tests/agent/test_roles.py -v`
- [ ] **Step 5:** `roles.py`'yi implement et: `Role` enum (MGR, ANL, DEV_FE, DEV_BE, QA, PM, SUP), her role için dataclass `RoleConfig(system_prompt, default_model, tool_names, max_steps)`
- [ ] **Step 6:** Test pass olduğunu doğrula
- [ ] **Step 7:** Commit: `git commit -m "feat(agent): bootstrap agent package with role definitions"`

#### Task 2: Agent database tables
**Files:**
- Create: `backend/alembic/versions/2026_07_25_xxxx_add_agent_tables.py`
- Create: `backend/app/models/conversation.py`
- Create: `backend/app/models/agent_run.py`
- Test: `backend/tests/agent/test_models.py`

- [ ] **Step 1:** `test_models.py` yaz — `Conversation`, `ConversationMessage`, `AgentRun` SQLModel field testleri
- [ ] **Step 2:** Test fail doğrula
- [ ] **Step 3:** Modelleri yaz (JSONB `messages`, FK → `tasks`/`process_runs`, indexes)
- [ ] **Step 4:** Alembic migration yaz (`conversations`, `conversation_messages`, `agent_runs`)
- [ ] **Step 5:** `alembic upgrade head` çalıştır
- [ ] **Step 6:** Test pass doğrula
- [ ] **Step 7:** Commit: `feat(db): agent runtime tables`

#### Task 3: Conversation store (PostgreSQL JSONB)
**Files:**
- Create: `backend/app/agent/memory.py`
- Test: `backend/tests/agent/test_memory.py`

- [ ] **Step 1:** Test yaz — `ConversationStore.append_message`, `get_messages`, `trim`, `summarize_if_needed`
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `ConversationStore` async class implement et (SQLAlchemy async session)
- [ ] **Step 4:** `trim(messages, max=30, files_read, files_created, files_edited)` — ApexAITeam pattern'i (system + last N + summary)
- [ ] **Step 5:** `summarize_if_needed(messages, threshold=50)` — basit extractive summary (Phase 7'de LLM-based ile değiştirilir)
- [ ] **Step 6:** Test pass
- [ ] **Step 7:** Commit: `feat(agent): conversation store with trim`

#### Task 4: Tool registry base
**Files:**
- Create: `backend/app/agent/tools/base.py`
- Create: `backend/app/agent/registry.py`
- Test: `backend/tests/agent/test_registry.py`

- [ ] **Step 1:** Test yaz — `Tool` dataclass, `register(tool)`, `get_tools_for_role(role)`
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `Tool` dataclass: `name, description, parameters_schema (JSON Schema), required_permissions, is_mutating, role_visibility`
- [ ] **Step 4:** `ToolRegistry` global singleton + `register`, `get`, `get_for_role`
- [ ] **Step 5:** Test pass
- [ ] **Step 6:** Commit: `feat(agent): tool registry base`

#### Task 5: 4-tier tool call parser
**Files:**
- Create: `backend/app/agent/tool_parser.py`
- Test: `backend/tests/agent/test_tool_parser.py`

- [ ] **Step 1:** Test yaz — 4 tier için ayrı test case'leri (regex, markdown JSON, balanced JSON, field extraction)
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `parse_tool_calls(text, schema)` implement et:
  - Tier 1: native `tool_calls` field (OpenAI/Anthropic format)
  - Tier 2: regex pattern `<tool_call>{...}</tool_call>` (Qwen/Ollama)
  - Tier 3: markdown JSON blocks (````json\n{...}\n````)
  - Tier 4: balanced-brace extraction (regex backtracking ile en uzun valid JSON)
- [ ] **Step 4:** Test pass
- [ ] **Step 5:** Commit: `feat(agent): 4-tier tool call parser`

#### Task 6: LiteLLM client wrapper
**Files:**
- Create: `backend/app/agent/llm/litellm_client.py`
- Create: `backend/app/agent/observability/activity_log.py`
- Test: `backend/tests/agent/test_litellm_client.py`

- [ ] **Step 1:** Test yaz (mocked litellm) — `completion()` returns standard response, token tracking callback fires
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `LiteLLMClient` class: `completion(model, messages, tools, **kwargs)` → returns `LLMResponse(content, tool_calls, usage, raw)`
- [ ] **Step 4:** Token tracking callback (`success_callback`): her çağrıda `token_usage` tablosuna INSERT (user_id, org_id, api_key_id, model, input_tokens, output_tokens, cost_usd)
- [ ] **Step 5:** Cost calculation helper (per-provider pricing dict, env-configurable)
- [ ] **Step 6:** Activity log helper (`log_activity(agent_run_id, role, level, message, metadata)`)
- [ ] **Step 7:** Test pass
- [ ] **Step 8:** Commit: `feat(agent): LiteLLM client with token tracking`

---

### Faz 2 — Tool Implementations (Tasks 7-15)

#### Task 7: read_file tool
**Files:**
- Create: `backend/app/agent/tools/read_file.py`
- Test: `backend/tests/agent/test_read_file.py`

- [ ] **Step 1:** Test yaz — happy path, file not found, file > N bytes (truncate), binary file reject
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `ReadFileTool(BaseTool)` — params: `path` (required), `start_line`, `end_line`
- [ ] **Step 4:** `ToolContext` inject (work_dir, allowed_paths); path traversal check
- [ ] **Step 5:** `is_mutating = False`, `role_visibility = ["MGR", "ANL", "DEV_FE", "DEV_BE", "QA", "PM", "SUP"]`
- [ ] **Step 6:** Register
- [ ] **Step 7:** Test pass
- [ ] **Step 8:** Commit: `feat(agent): read_file tool`

#### Task 8: list_dir + grep_search tools
**Files:**
- Create: `backend/app/agent/tools/list_dir.py`
- Create: `backend/app/agent/tools/grep_search.py`
- Test: `backend/tests/agent/test_list_dir.py`, `test_grep_search.py`

- [ ] Her ikisi için TDD cycle: test → fail → implement → pass → commit
- [ ] `list_dir`: params `path`, `recursive`, `pattern` (glob); output JSON tree
- [ ] `grep_search`: ripgrep wrapper subprocess; params `pattern`, `path`, `include_glob`, `context_lines`; output match list

#### Task 9: ast_grep tool
**Files:**
- Create: `backend/app/agent/tools/ast_grep.py`
- Test: `backend/tests/agent/test_ast_grep.py`

- [ ] **Step 1:** Test (Python, JS, Go için ayrı pattern case)
- [ ] **Step 2:** `AstGrepTool` — `pattern` (ast-grep syntax), `language` (auto-detect), `path`
- [ ] **Step 3:** subprocess call `ast-grep run --pattern <pattern> --lang <lang> <path>`
- [ ] **Step 4:** Output → structured matches (file, line, column, code snippet)
- [ ] **Step 5:** Test pass + commit

#### Task 10: write_file tool (intentionalFiles + 50% reject)
**Files:**
- Create: `backend/app/agent/tools/write_file.py`
- Test: `backend/tests/agent/test_write_file.py`

- [ ] **Step 1:** Test yaz — yeni dosya OK, existing dosyaya full overwrite eğer existing <50% ise OK, değilse reject
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `WriteFileTool` — params `path`, `content`
- [ ] **Step 4:** Pre-check: existing dosya varsa → `existing_size vs new_size`; new <50% existing → `BLOCKED: <reason>; use edit_file`
- [ ] **Step 5:** `intentionalFiles` add (ToolContext'te `record_intentional_file(path)`)
- [ ] **Step 6:** `is_mutating = True`, `required_permissions = [Permission.TASKS_CREATE]`
- [ ] **Step 7:** Audit log INSERT (`file.written`)
- [ ] **Step 8:** Test pass + commit

#### Task 11: edit_file tool (search-replace engine)
**Files:**
- Create: `backend/app/agent/tools/edit_file.py`
- Test: `backend/tests/agent/test_edit_file.py`

- [ ] **Step 1:** Test yaz — Aider-style search-replace block, multiple blocks in one call, fuzzy match tolerance, block not found error
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `EditFileTool` — params `path`, `edits` (list of `{old_text, new_text}`) veya single edit
- [ ] **Step 4:** Parse format:
  ```
  <<<<<<< SEARCH
  old_text
  =======
  new_text
  >>>>>>> REPLACE
  ```
- [ ] **Step 5:** Exact match → replace; değilse whitespace-normalized match; değilse fuzzy match (difflib.SequenceMatcher, ratio > 0.85)
- [ ] **Step 6:** All edits atomic (success → write; any fail → no write, return error)
- [ ] **Step 7:** Audit log + intentionalFiles tracking
- [ ] **Step 8:** Test pass + commit

#### Task 12: run_command tool (sandboxed subprocess)
**Files:**
- Create: `backend/app/agent/tools/run_command.py`
- Test: `backend/tests/agent/test_run_command.py`

- [ ] **Step 1:** Test yaz — happy path, timeout, non-zero exit, command blocklist (rm -rf, sudo, etc.), work_dir chroot
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `RunCommandTool` — params `command`, `cwd`, `timeout_seconds` (max 120), `env_overrides`
- [ ] **Step 4:** Blocklist: regex `r'\b(rm\s+-rf|sudo|chmod\s+777|mkfs|dd\s+if=|curl.*\|.*sh)\b'`
- [ ] **Step 5:** subprocess.run with `cwd=work_dir`, `shell=True`, `timeout`, capture stdout/stderr
- [ ] **Step 6:** Resource limit: `resource.setrlimit(RLIMIT_CPU, (60, 60))` (POSIX only, Linux k8s)
- [ ] **Step 7:** Output truncation (last 50KB)
- [ ] **Step 8:** Test pass + commit

#### Task 13: git_status + git_diff tools
**Files:**
- Create: `backend/app/agent/tools/git_status.py`
- Create: `backend/app/agent/tools/git_diff.py`
- Test: `backend/tests/agent/test_git_*.py`

- [ ] Her ikisi: subprocess `git status` / `git diff` in work_dir, structured output
- [ ] `git_status`: parsed JSON (branch, staged, unstaged, untracked)
- [ ] `git_diff`: optional `-- path`, output diff text (cap 50KB)

#### Task 14: run_subagent tool
**Files:**
- Create: `backend/app/agent/tools/run_subagent.py`
- Test: `backend/tests/agent/test_run_subagent.py`

- [ ] **Step 1:** Test yaz — sub-agent runs, returns summary, max depth 2 enforced
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `RunSubagentTool` — params `prompt`, `role` (defaults to DEV), `max_steps` (max 15)
- [ ] **Step 4:** Recursive call to `AgentLoop.run()` with isolated context
- [ ] **Step 5:** Depth check: `if agent_run.depth >= 2: raise ToolError("subagent depth exceeded")`
- [ ] **Step 6:** Test pass + commit

#### Task 15: Tool permission gate
**Files:**
- Create: `backend/app/agent/gates.py`
- Test: `backend/tests/agent/test_gates.py`

- [ ] **Step 1:** Test yaz — write tool requires `TASKS_CREATE`, run_command requires `TASKS_CREATE`, missing perm → `ToolPermissionError`
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `ToolPermissionGate.check(tool, user_context)` — `tool.required_permissions ⊆ user.permissions`
- [ ] **Step 4:** Integration with `ToolExecutor._execute` (before sandbox run)
- [ ] **Step 5:** Audit log `tool.permission_denied`
- [ ] **Step 6:** Test pass + commit

---

### Faz 3 — Safety Systems (Tasks 16-19)

#### Task 16: Circuit breaker
**Files:**
- Create: `backend/app/agent/safety.py`
- Test: `backend/tests/agent/test_safety.py`

- [ ] **Step 1:** Test yaz — 3 consecutive same-tool failures → `CircuitBreakerTripped`, inject guidance message, reset on success
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `CircuitBreaker(max_consecutive=3)` — `record_failure(tool_name)`, `record_success()`, `tripped` property, `guidance_message()`
- [ ] **Step 4:** Trip olduğunda conversation'a inject: `"⚠️ Tool X failed 3 times in a row. Try a different approach."`
- [ ] **Step 5:** Test pass + commit

#### Task 17: Repetition detector
**Files:**
- Modify: `backend/app/agent/safety.py`
- Test: extend `test_safety.py`

- [ ] **Step 1:** Test yaz — 6× aynı mutating tool çağrısı → `finish`, read-only tool için 12× limit
- [ ] **Step 2:** `RepetitionDetector` — separate counters for read-only vs mutating
- [ ] **Step 3:** Read-only tools için `tool+arg` key (farklı dosyalar aynı sayılmaz)
- [ ] **Step 4:** Mutating tools için sadece tool name
- [ ] **Step 5:** Test pass + commit

#### Task 18: Edit failure tracker
**Files:**
- Modify: `backend/app/agent/safety.py`
- Test: extend `test_safety.py`

- [ ] **Step 1:** Test yaz — 5 cumulative edit tool failures (read'ler reset etmez) → `EditFailureLimitReached`, inject guidance
- [ ] **Step 2:** `EditFailureTracker` — `record_failure(tool_name)`, `is_exceeded` (5), `guidance`
- [ ] **Step 3:** Edit tools set: `{write_file, edit_file, replace_string_in_file, apply_patch, insert_edit_into_file}`
- [ ] **Step 4:** Test pass + commit

#### Task 19: Token budget enforcer
**Files:**
- Create: `backend/app/agent/safety.py` (extend)
- Test: extend `test_safety.py`

- [ ] **Step 1:** Test yaz — input tokens accumulate; per-run limit (e.g. 500K) → abort with summary; per-org daily cap → 429-ish error
- [ ] **Step 2:** `TokenBudgetEnforcer` — `record_usage(input, output)`, `is_run_exceeded`, `is_org_daily_exceeded`
- [ ] **Step 3:** Source daily cap from `settings` table (`ai.daily_token_budget.<org_id>`)
- [ ] **Step 4:** Test pass + commit

---

### Faz 4 — Agent Loop Core (Tasks 20-26)

#### Task 20: AgentLoop dataclass config
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: `backend/tests/agent/test_runtime.py`

- [ ] **Step 1:** Test yaz — `AgentLoopConfig` dataclass fields, defaults, role+model resolution
- [ ] **Step 2:** `AgentLoopConfig`: `agent_run_id, role, user_prompt, work_dir, allowed_paths, max_steps, provider, model, parent_run_id`
- [ ] **Step 3:** Resolve provider/model: `settings.ai.default_provider/model` (user override > org override > platform default)
- [ ] **Step 4:** Test pass + commit

#### Task 21: AgentLoop.run() main loop
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: extend `test_runtime.py`

- [ ] **Step 1:** Test (mocked LLM) — happy path: 3 step loop, finish tool çağrıldığında loop çıkar
- [ ] **Step 2:** Test fail
- [ ] **Step 3:** `AgentLoop.run(config) -> AgentResult` — main loop (ApexAITeam AgentRuntime.RunAgentLoop benzeri)
- [ ] **Step 4:** Step flow: trim → log → call LLM → append response → execute tool calls → append results → check breakers → repeat
- [ ] **Step 5:** `finish` tool → break loop with summary
- [ ] **Step 6:** Max steps exceeded → graceful exit with partial summary
- [ ] **Step 7:** Test pass + commit

#### Task 22: AgentLoop tool call parsing integration
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: extend `test_runtime.py`

- [ ] **Step 1:** Test — LLM returns text with embedded tool calls (Qwen style) → parser extracts, executor runs
- [ ] **Step 2:** Integration with `tool_parser.parse_tool_calls()`
- [ ] **Step 3:** Test pass + commit

#### Task 23: AgentLoop conversation management
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: extend `test_runtime.py`

- [ ] **Step 1:** Test — messages persist between steps; trim occurs at threshold; summary injected when >50 messages
- [ ] **Step 2:** `ConversationStore.append_message` after each LLM call + tool result
- [ ] **Step 3:** `trim()` before each LLM call
- [ ] **Step 4:** Test pass + commit

#### Task 24: AgentLoop safety integration
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: extend `test_runtime.py`

- [ ] **Step 1:** Test — circuit breaker trips after 3 fails, repetition detector at 6 calls, edit tracker at 5, token budget enforced
- [ ] **Step 2:** Wire all 4 safety modules into main loop
- [ ] **Step 3:** Each trip/abort → inject guidance → continue OR finish
- [ ] **Step 4:** Test pass + commit

#### Task 25: AgentLoop activity logging
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: extend `test_runtime.py`

- [ ] **Step 1:** Test — `log_activity(agent_run_id, role, level, message, metadata)` called at every step boundary
- [ ] **Step 2:** Log events: `agent.started`, `ai.request`, `ai.thinking`, `tool.call`, `tool.result`, `safety.tripped`, `agent.finished`
- [ ] **Step 3:** Activity log → `audit_log` (F) ile aynı tabloya actor_type=`agent` olarak yaz
- [ ] **Step 4:** Test pass + commit

#### Task 26: AgentResult dataclass + summary
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: extend `test_runtime.py`

- [ ] **Step 1:** Test — `AgentResult(success, summary, steps, total_tokens, intentional_files, error)`
- [ ] **Step 2:** Implement `AgentResult` + summary generation (last assistant content + files touched list)
- [ ] **Step 3:** Update `agent_runs` row with end status, token totals, duration
- [ ] **Step 4:** Test pass + commit

---

### Faz 5 — Role Configuration & SOLUTION.md (Tasks 27-32)

#### Task 27: Per-role system prompts
**Files:**
- Create: `backend/app/agent/prompts/` (yeni dizin)
- Create: `backend/app/agent/prompts/manager.py`, `analyst.py`, `developer_fe.py`, `developer_be.py`, `qa.py`, `pm.py`, `support.py`
- Test: `backend/tests/agent/test_prompts.py`

- [ ] **Step 1:** Test — `Role.MGR.system_prompt` returns non-empty string, contains role-specific instructions
- [ ] **Step 2:** Her role için system prompt yaz (ApexAITeam AgentPrompts.cs port):
  - **MGR**: Workspace orchestration, routing, git+PR, no direct code editing
  - **ANL**: Project analysis, plan generation, reads only, no edits
  - **DEV_FE**: React/Next.js/CSS/UI, can read/write/edit/run_command (npm)
  - **DEV_BE**: Python/FastAPI/DB/Go/Rust, can read/write/edit/run_command (pytest)
  - **QA**: Build + lint + test, runs validators, doesn't write code
  - **PM**: Spec refinement, story creation, no code
  - **SUP**: Investigation, log analysis, can run read-only
- [ ] **Step 3:** Her prompt contains: role description, available tools list (filtered), workflow instructions, "call finish when done"
- [ ] **Step 4:** Test pass + commit

#### Task 28: Per-role tool visibility
**Files:**
- Modify: `backend/app/agent/roles.py`
- Test: extend `test_roles.py`

- [ ] **Step 1:** Test — `Role.MGR.tools` returns correct subset (read, list, grep, ast_grep, git_status, git_diff, run_subagent — NO write_file/edit_file/run_command)
- [ ] **Step 2:** Configure `tool_names` per role in `roles.py`
- [ ] **Step 3:** Test pass + commit

#### Task 29: SOLUTION.md generator
**Files:**
- Create: `backend/app/agent/analysis/solution_md.py`
- Test: `backend/tests/agent/test_solution_md.py`

- [ ] **Step 1:** Test — generates 10-section markdown for Python+FastAPI project, capped at 2000 lines, idempotent (skip if exists)
- [ ] **Step 2:** Sections: tech stack, build commands, deep AST analysis per language, test commands, lint commands, env vars, deployment notes
- [ ] **Step 3:** Auto-detect via manifests (package.json, pyproject.toml, go.mod, Cargo.toml, pom.xml)
- [ ] **Step 4:** ast-grep call per language for top-level structure
- [ ] **Step 5:** Cache check (skip if SOLUTION.md exists & < 7 days old)
- [ ] **Step 6:** Test pass + commit

#### Task 30: Migration approval gate
**Files:**
- Create: `backend/app/agent/gates.py` (extend)
- Test: `backend/tests/agent/test_migration_gate.py`

- [ ] **Step 1:** Test — `run_command` tool detects `alembic upgrade`, `prisma migrate`, etc., pauses loop, returns pending state
- [ ] **Step 2:** `MigrationGate.detect(command) -> bool`
- [ ] **Step 3:** Loop integration: tool result `IsMigrationPending=True` → write `agent_run.status = "awaiting_approval"`, exit loop
- [ ] **Step 4:** Approval endpoint (Faz 6'da) resumes loop
- [ ] **Step 5:** Test pass + commit

#### Task 31: Plan approval gate (between ANL → DEV)
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: extend `test_runtime.py`

- [ ] **Step 1:** Test — ANL generates plan → loop exits with `awaiting_approval`, after approval DEV picks up
- [ ] **Step 2:** ANL `finish` tool returns structured `PlanOutput` JSON
- [ ] **Step 3:** Persist plan in `conversations.metadata.plan`
- [ ] **Step 4:** Resume mechanism (resume from agent_run_id)
- [ ] **Step 5:** Test pass + commit

#### Task 32: PR-rejection revision loop
**Files:**
- Modify: `backend/app/agent/prompts/developer_fe.py`, `developer_be.py`
- Test: extend `test_prompts.py`

- [ ] **Step 1:** Test — when `pr.rejected` event fires with feedback, system prompt augmented with "fix per PR feedback" + wider step limit (100 vs 40)
- [ ] **Step 2:** `RoleConfig` has `max_steps_normal`, `max_steps_revision`; revision context switches them
- [ ] **Step 3:** Test pass + commit

---

### Faz 6 — Agent REST API (Tasks 33-39)

#### Task 33: Schemas
**Files:**
- Create: `backend/app/schemas/agent.py`
- Test: `backend/tests/agent/test_schemas.py`

- [ ] **Step 1:** Test yaz — `ConverseRequest`, `ConverseResponse` Pydantic schemas
- [ ] **Step 2:** `ConverseRequest`: `task_id, role, prompt, work_dir, model_override, max_steps_override, stream`
- [ ] **Step 3:** `ConverseResponse`: `agent_run_id, success, summary, steps[], total_tokens, intentional_files[], error`
- [ ] **Step 4:** Test pass + commit

#### Task 34: POST /agent/converse (sync)
**Files:**
- Create: `backend/app/agent/api/routes.py`
- Test: `backend/tests/agent/test_api.py`

- [ ] **Step 1:** Test — endpoint accepts request, calls `AgentLoop.run`, returns response
- [ ] **Step 2:** Auth dependency (`get_current_user`), permission check (`TASKS_CREATE`)
- [ ] **Step 3:** Resolve AI key via F's `resolve_ai_key(org_id, user_id, provider)`
- [ ] **Step 4:** Run `AgentLoop.run()`, persist `agent_runs` row
- [ ] **Step 5:** Return `ConverseResponse`
- [ ] **Step 6:** Test pass + commit

#### Task 35: POST /agent/converse/stream (SSE)
**Files:**
- Modify: `backend/app/agent/api/routes.py`
- Test: extend `test_api.py`

- [ ] **Step 1:** Test — SSE stream emits events per step
- [ ] **Step 2:** Event types: `agent.started`, `ai.thinking`, `tool.call`, `tool.result`, `agent.finished`
- [ ] **Step 3:** Use FastAPI `StreamingResponse` with `text/event-stream`
- [ ] **Step 4:** Test pass + commit

#### Task 36: GET /agent/runs/{id}
**Files:**
- Modify: `backend/app/agent/api/routes.py`
- Test: extend `test_api.py`

- [ ] **Step 1:** Test — returns `agent_run` with conversation messages + activity log
- [ ] **Step 2:** RBAC: user can see own runs; org admin/manager sees all in org; cross-org forbidden
- [ ] **Step 3:** Test pass + commit

#### Task 37: POST /agent/runs/{id}/resume (approval gates)
**Files:**
- Modify: `backend/app/agent/api/routes.py`
- Test: extend `test_api.py`

- [ ] **Step 1:** Test — resumes paused loop with approval body `{plan_approved: true, comment?}` or migration approval
- [ ] **Step 2:** Load agent_run, append approval message to conversation, continue loop from checkpoint
- [ ] **Step 3:** Audit log `agent.resumed`
- [ ] **Step 4:** Test pass + commit

#### Task 38: API key resolution integration
**Files:**
- Modify: `backend/app/agent/runtime.py`
- Test: extend `test_runtime.py`

- [ ] **Step 1:** Test — `LiteLLMClient.completion` calls `resolve_ai_key(org_id, user_id, provider)`, passes API key to litellm
- [ ] **Step 2:** Use F's `app.core.vault.VaultClient.read`
- [ ] **Step 3:** Test pass + commit

#### Task 39: Mount routes in main app
**Files:**
- Modify: `backend/app/main.py`
- Test: integration smoke

- [ ] **Step 1:** `from app.agent.api.routes import router as agent_router`
- [ ] **Step 2:** `app.include_router(agent_router, prefix="/api/v1/agent", tags=["agent"])`
- [ ] **Step 3:** `curl localhost:8000/docs` → agent endpoints listeleniyor
- [ ] **Step 4:** Commit: `feat(api): mount agent routes`

---

### Faz 7 — Conversation Memory Advanced (Tasks 40-43)

#### Task 40: Token-aware trimming
**Files:**
- Modify: `backend/app/agent/memory.py`
- Test: extend `test_memory.py`

- [ ] **Step 1:** Test — trim by token count (not message count) using tiktoken
- [ ] **Step 2:** `trim(messages, max_tokens=8000)` — system + recent + oldest summary
- [ ] **Step 3:** Per-role max_tokens config (MGR 4K, DEV 16K, QA 8K)
- [ ] **Step 4:** Test pass + commit

#### Task 41: Extractive summary
**Files:**
- Modify: `backend/app/agent/memory.py`
- Test: extend `test_memory.py`

- [ ] **Step 1:** Test — when messages > N, oldest replaced with summary containing: files touched list, decisions made, errors encountered
- [ ] **Step 2:** Pure Python extractive (no LLM call): regex extract file paths, decision phrases ("I'll use...", "decided to..."), error messages
- [ ] **Step 3:** Summary structured: `{"files_read": [...], "files_written": [...], "decisions": [...], "errors": [...]}`
- [ ] **Step 4:** Test pass + commit

#### Task 42: Conversation branching (sub-agents)
**Files:**
- Modify: `backend/app/agent/memory.py`
- Test: extend `test_memory.py`

- [ ] **Step 1:** Test — sub-agent has own conversation branch; parent → child link via `parent_message_id`
- [ ] **Step 2:** `conversation_messages.parent_id` FK
- [ ] **Step 3:** On `run_subagent`, branch from current message
- [ ] **Step 4:** Test pass + commit

#### Task 43: Conversation export
**Files:**
- Create: `backend/app/agent/memory.py` (extend)
- Test: extend `test_memory.py`

- [ ] **Step 1:** Test — export conversation as JSON (for debugging, audit, replay)
- [ ] **Step 2:** `export(agent_run_id) -> dict` with full message tree
- [ ] **Step 3:** `GET /agent/runs/{id}/export` endpoint
- [ ] **Step 4:** Test pass + commit

---

### Faz 8 — Testing, Observability, Documentation (Tasks 44-50)

#### Task 44: Integration test — full loop
**Files:**
- Create: `backend/tests/agent/test_integration.py`

- [ ] **Step 1:** Test — happy path: ANL analyzes a fixture project, generates plan, exit `awaiting_approval`; resume with approval → DEV implements → finish
- [ ] **Step 2:** Mock LiteLLM responses (deterministic)
- [ ] **Step 3:** Real tool execution against fixture (small repo with package.json, pyproject.toml)
- [ ] **Step 4:** Verify `agent_runs` rows, `conversation_messages`, `token_usage`, `audit_log` all populated correctly
- [ ] **Step 5:** Test pass + commit

#### Task 45: Integration test — failure modes
**Files:**
- Create: `backend/tests/agent/test_failure_modes.py`

- [ ] **Step 1:** Test — circuit breaker trip, repetition detector trip, edit failure tracker, token budget exceeded, migration approval gate
- [ ] **Step 2:** Each scenario: loop exits with expected status, activity log has correct entries
- [ ] **Step 3:** Test pass + commit

#### Task 46: Performance test — token budget enforcement
**Files:**
- Create: `backend/tests/agent/test_perf.py`

- [ ] **Step 1:** Test — agent run with mocked LLM that returns huge responses; verify budget enforced before overflow
- [ ] **Step 2:** Test pass + commit

#### Task 47: Prometheus metrics
**Files:**
- Create: `backend/app/agent/observability/metrics.py`

- [ ] **Step 1:** Counter `agent_runs_total{role,status}`, Histogram `agent_loop_duration_seconds{role}`, Counter `agent_tokens_total{role,provider,model}`
- [ ] **Step 2:** Wire into `AgentLoop.run`
- [ ] **Step 3:** `/metrics` endpoint expose
- [ ] **Step 4:** Commit

#### Task 48: OpenTelemetry tracing
**Files:**
- Modify: `backend/app/agent/runtime.py`

- [ ] **Step 1:** Span per `AgentLoop.run`; child spans per LLM call, per tool execution
- [ ] **Step 2:** Attributes: `agent_run_id, role, model, tool_name, duration, token_count`
- [ ] **Step 3:** Test (jaeger exporter in dev)
- [ ] **Step 4:** Commit

#### Task 49: A spec document finalized
**Files:**
- Create: `docs/superpowers/specs/2026-07-25-agent-runtime-design.md`

- [ ] **Step 1:** Bu plan dosyasından spec'i çıkar (Phase 0'da: amaç, kapsam, mimari, DB tabloları, API surface, tech stack, kararlar)
- [ ] **Step 2:** Spec'e ekle: deployment (k8s), CI/CD, monitoring
- [ ] **Step 3:** Spec'i `docs/superpowers/specs/`'e koy
- [ ] **Step 4:** Commit

#### Task 50: Update root README + agent docs
**Files:**
- Modify: `README.md`
- Create: `docs/agent-runtime.md`

- [ ] **Step 1:** README'de "Agent Runtime" section — capabilities, how to invoke
- [ ] **Step 2:** `docs/agent-runtime.md` — architecture diagram, tool list, role descriptions, examples
- [ ] **Step 3:** Commit

---

### Faz 9 — Production Readiness (Tasks 51-58)

#### Task 51: Docker image for agent runtime
**Files:**
- Modify: `backend/Dockerfile`

- [ ] **Step 1:** Add `ast-grep` binary install (npm global)
- [ ] **Step 2:** Add `ripgrep` (`apt-get install ripgrep`)
- [ ] **Step 3:** Multi-stage build (uv cache layer)
- [ ] **Step 4:** Commit

#### Task 52: Rate limit handling (Tenacity)
**Files:**
- Modify: `backend/app/agent/llm/litellm_client.py`

- [ ] **Step 1:** Tenacity decorator with exponential backoff: 30s → 60s → 120s → max 300s, max 5 retries
- [ ] **Step 2:** Per-provider config: Anthropic stricter (2 retries), Ollama looser (5 retries)
- [ ] **Step 3:** Test (mocked 429 responses)
- [ ] **Step 4:** Commit

#### Task 53: Streaming responses
**Files:**
- Modify: `backend/app/agent/llm/litellm_client.py`

- [ ] **Step 1:** `completion_stream(model, messages, tools)` returns async iterator of chunks
- [ ] **Step 2:** Each chunk: `{delta_content, delta_tool_call, finish_reason}`
- [ ] **Step 3:** Wire into SSE endpoint
- [ ] **Step 4:** Commit

#### Task 54: Helm chart update (agent replicas)
**Files:**
- Modify: `deploy/helm/values.yaml`, `fastapi-deployment.yaml`

- [ ] **Step 1:** FastAPI replicas: 3 (same as F)
- [ ] **Step 2:** Resource limits: 500m–2Gi CPU, 512Mi–2Gi memory (LLM calls heavier)
- [ ] **Step 3:** Commit

#### Task 55: Health checks for agent endpoints
**Files:**
- Modify: `backend/app/agent/api/routes.py`

- [ ] **Step 1:** `/api/v1/agent/health` — LiteLLM client warm, DB reachable, no stuck runs
- [ ] **Step 2:** `/api/v1/agent/ready` — same + at least one role prompt loads
- [ ] **Step 3:** Commit

#### Task 56: Cleanup of stuck runs
**Files:**
- Create: `backend/app/agent/cleanup.py`

- [ ] **Step 1:** Background task (every 5min) — find `agent_runs` with `status='running'` and `started_at < now() - 1h` → mark `stuck`, log warning
- [ ] **Step 2:** Manual `/api/v1/agent/runs/{id}/cancel` endpoint
- [ ] **Step 3:** Test + commit

#### Task 57: Agent admin endpoints (platform admin)
**Files:**
- Modify: `backend/app/agent/api/routes.py`

- [ ] **Step 1:** `GET /api/v1/agent/runs` — list all runs in org, filter by role/status/date
- [ ] **Step 2:** `GET /api/v1/platform/agent/stats` — platform admin: total runs, tokens, cost
- [ ] **Step 3:** RBAC enforcement
- [ ] **Step 4:** Commit

#### Task 58: End-to-end smoke test
**Files:**
- Create: `backend/tests/agent/test_e2e.py`

- [ ] **Step 1:** Spin up real FastAPI + Postgres + Vault (testcontainers)
- [ ] **Step 2:** Create user/org, login, call `/agent/converse` with mocked LiteLLM, verify full DB state
- [ ] **Step 3:** Verify audit log entries, token_usage rows, agent_run metadata
- [ ] **Step 4:** Test pass + commit

---

### Faz 10 — F'den Kalan Cross-Cutting Integration (Tasks 59-65)

#### Task 59: User preference injection (C.3 prep)
**Files:**
- Modify: `backend/app/agent/llm/litellm_client.py`

- [ ] **Step 1:** `completion()` injects `user_preferences.style_profile` into system prompt
- [ ] **Step 2:** Stub: if `user_preferences` table doesn't exist yet, no-op
- [ ] **Step 3:** Test + commit

#### Task 60: Org default model from settings
**Files:**
- Modify: `backend/app/agent/roles.py`

- [ ] **Step 1:** `RoleConfig.default_model` resolved from settings (org > platform)
- [ ] **Step 2:** Admin override enforced (`enforced_by_admin=True` → user pref ignored)
- [ ] **Step 3:** Test + commit

#### Task 61: Token budget dashboard (stub for G)
**Files:**
- Create: `backend/app/agent/api/routes.py` (extend)

- [ ] **Step 1:** `GET /api/v1/agent/usage/summary?period=7d` — total tokens, cost, by role/model
- [ ] **Step 2:** Read from `token_usage` table
- [ ] **Step 3:** Test + commit

#### Task 62: Agent output caching (Redis)
**Files:**
- Create: `backend/app/agent/cache.py`

- [ ] **Step 1:** `cache_get(prompt_hash) -> cached_response | None`
- [ ] **Step 2:** Hash: SHA256 of (model + system_prompt + user_prompt)
- [ ] **Step 3]** Optional: enabled via setting `ai.cache_enabled`
- [ ] **Step 4:** Test + commit

#### Task 63: Failure recovery (resume after worker crash)
**Files:**
- Modify: `backend/app/agent/runtime.py`

- [ ] **Step 1:** On startup, find `agent_runs.status='running'`, mark as `interrupted`
- [ ] **Step 2:** User can `/agent/runs/{id}/resume` to restart from last successful checkpoint
- [ ] **Step 3:** Test + commit

#### Task 64: Agent versioning
**Files:**
- Modify: `backend/app/agent/roles.py`

- [ ] **Step 1:** `RoleConfig.version` field; system prompts in `prompts/<role>.py` versioned
- [ ] **Step 2:** `agent_runs.prompt_version` captured at start
- [ ] **Step 3:** Test + commit

#### Task 65: Documentation site contribution
**Files:**
- Create: `docs/superpowers/specs/2026-07-25-agent-runtime-design.md` (final)

- [ ] **Step 1:** Move this plan content into proper spec (background, decisions, deployment)
- [ ] **Step 2:** Link from F spec §13 (cross-references)
- [ ] **Step 3:** Commit

---

### Faz 11 — Quality Gates & Final Validation (Tasks 66-70)

#### Task 66: Linting + type checking
**Files:**
- Modify: `pyproject.toml`, `.pre-commit-config.yaml`

- [ ] **Step 1:** `ruff check`, `ruff format`, `mypy --strict` on `app/agent/**`
- [ ] **Step 2:** Pre-commit hooks
- [ ] **Step 3:** CI workflow runs all
- [ ] **Step 4:** Commit

#### Task 67: Coverage gate
**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1:** pytest-cov configured; `--cov-fail-under=80` for `app/agent/**`
- [ ] **Step 2:** Commit

#### Task 68: Load test — concurrent agent runs
**Files:**
- Create: `backend/tests/agent/test_load.py`

- [ ] **Step 1:** Locust script — 50 concurrent `/agent/converse` calls
- [ ] **Step 2:** Verify token budget enforced, no DB connection exhaustion, rate limits respected
- [ ] **Step 3:** Commit

#### Task 69: Security audit
**Files:**
- Create: `docs/security-agent-runtime.md`

- [ ] **Step 1:** Sandbox escape attempts (path traversal, command injection, resource exhaustion)
- [ ] **Step 2:** RBAC enforcement at every endpoint
- [ ] **Step 3:** API key not logged in any path
- [ ] **Step 4:** Commit findings + fixes

#### Task 70: Spec self-review + final commit
**Files:**
- Modify: `docs/superpowers/specs/2026-07-25-agent-runtime-design.md`

- [ ] **Step 1:** Spec coverage table — her bölüm için task referansı
- [ ] **Step 2:** Karar geçmişi güncelle
- [ ] **Step 3:** Açık sorular (ileride): pgvector entegrasyonu, multimodal model'ler, fine-tuning pipeline
- [ ] **Step 4:** Final commit: `feat(agent): sub-system A complete`

---

## Spec Coverage Tablosu (Final)

| Spec Section | Implementation Tasks |
|---|---|
| Role-based specialists | 1, 20, 27, 28 |
| Multi-provider model abstraction | 6, 38, 52, 53 |
| Conversation memory | 3, 23, 40, 41, 42, 43 |
| Tool execution + sandbox | 7-15, 51 |
| Code editing (search-replace) | 11 |
| Token tracking + cost | 6, 19, 38, 61 |
| Safety systems | 16, 17, 18, 19 |
| Approval gates | 30, 31, 32, 37 |
| SOLUTION.md | 29 |
| REST API (sync + stream) | 33, 34, 35, 36, 37, 39, 55, 57 |
| Production readiness | 51-58 |
| Observability | 25, 47, 48 |
| Testing | 44, 45, 46, 58, 67, 68 |
| Documentation | 49, 50, 69, 70 |

---

## Doğrulama (Verification)

### Local development
```bash
cd apexai
uv sync
docker compose -f deploy/docker-compose.dev.yml up -d
cd backend
alembic upgrade head
uv run pytest tests/agent/ -v --cov=app/agent --cov-fail-under=80
uv run uvicorn app.main:app --reload
# Open http://localhost:8000/docs → verify agent endpoints listed
```

### Smoke test (end-to-end)
```bash
# 1. Login (F endpoint)
TOKEN=$(curl -X POST localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"test"}' \
  -c cookies.txt | jq -r '.access_token')

# 2. Create task, invoke agent
curl -X POST localhost:8000/api/v1/agent/converse \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "task_id": "<uuid>",
    "role": "ANL",
    "prompt": "Analyze this repo and suggest 3 improvements",
    "work_dir": "/tmp/test-repo"
  }' | jq .

# 3. Verify in DB
psql -d apexai -c "SELECT role, status, total_tokens FROM agent_runs ORDER BY started_at DESC LIMIT 5;"
psql -d apexai -c "SELECT provider, model, input_tokens, output_tokens, cost_usd FROM token_usage ORDER BY created_at DESC LIMIT 5;"
```

### Production deployment
```bash
helm upgrade --install apexai deploy/helm/ \
  --values deploy/helm/values.prod.yaml \
  --set agentRuntime.replicas=3
kubectl get pods -l app=apex-fastapi -w
curl https://apexai.example.com/api/v1/agent/health
```

---

## Açık Sorular (Sonraki Session'lara)

Bu plan A'yı production-ready yapar, ama şu konular B-G ile birlikte veya sonrasında ele alınacak:

1. **B (Workflow Orchestration)** — agent loop'un queue'dan nasıl tetikleneceği, multi-step process state machine, retry/DLQ
2. **C (Task Dashboard)** — agent_run'ların UI'da görselleştirilmesi, real-time updates
3. **D (Cost Cascade)** — heuristic → semantic → LightGBM → LLM routing — A'nın `completion()` çağrısını sardığı için direkt A'ya bağımlı
4. **E (Build Pipeline)** — `run_command` tool'unun k8s sandbox runner versiyonu
5. **G (Frontend)** — agent chat UI, task kanban, real-time SSE consumer
6. **Multimodal** — vision models (image input), code-as-image
7. **Fine-tuning** — org-specific model adaptation pipeline (C.3 user feedback aggregation)
8. **Vector embeddings** — `semantic_search` tool için pgvector entegrasyonu (Phase 7'de stub, sonra full)

---

## Repo Setup (Plan Onayından Sonra)

Plan onaylandığında:

```bash
cd /Users/macbook/WorkSpaces/Individual/ApexAI
git init  # zaten var, skip
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/iskyldrm/ApexAI.git
git branch -M main
# Eğer branch master ise:
git checkout -b main
# İlk push (F docs zaten commit edilmiş)
git push -u origin main
```

Ardından execution başlar:
```bash
# F Phase 0 execute (Tasks 1-7) — ayrı session'da
# A Phase 1 execute (Tasks 1-6) — bu planın başlangıcı
```

---

## Self-Review Checklist (Plan Kalitesi)

- [x] Her task'ta TDD cycle (test → fail → implement → pass → commit)
- [x] Exact file paths her task'ta
- [x] Commit per task
- [x] Type/method consistency (Tool dataclass her yerde aynı)
- [x] F spec coverage (api_keys, token_usage, audit_log tüketiliyor)
- [x] ApexAITeam patterns port ediliyor (6 pattern açıkça)
- [x] ApexAITeam anti-pattern'lerden kaçınılıyor (4 anti-pattern açıkça)
- [x] No placeholders (her task concrete)
- [x] Spec coverage tablosu final bölümde
- [x] Verification section concrete (smoke test, k8s deploy)
- [x] Açık sorular gelecek session'lara açıkça devrediliyor

---

**Plan durumu:** Ready for execution after approval. Estimated effort: 70 tasks × ~15-30min/task = ~20-35 hours (1 engineer, subagent-driven). Token budget: ~500K-800K tokens for subagent-driven execution.
