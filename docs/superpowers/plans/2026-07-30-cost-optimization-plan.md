# ApexAI — Sub-System D (Cost Optimization) Implementation Plan

> **Goal:** route every LLM call through the cheapest model that can handle it, enforce per-org / per-user budgets, and surface spend insights.
> **Depends on:** Sub-System A (LiteLLMClient + TokenBudgetEnforcer), Sub-System C (notifications for budget alerts)

---

## Context

Sub-System A's `LiteLLMClient` currently sends every call to one fixed model (resolved from env: Ollama / MiniMax / gpt-4o). When operators want to mix providers — small `llama3.2` for simple lookups, expensive `claude-opus` for planning — they have no knob per-call.

ApexAITeam shipped a 3-tier router (heuristic → semantic → LLM) that reduced cost ~40% with no measurable quality regression. We port it.

---

## Decisions

| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Routing strategy | **Heuristic first (cost = 0), semantic if uncertain, LLM fallback** | Cheapest path wins; semantic only when needed |
| 2 | Heuristic signals | Length + keyword scan (e.g. "translate", "summarize" → small model; "design", "review" → big model) | No API cost, microseconds |
| 3 | Semantic router | sentence-transformers embedding + cosine similarity to class centroids | Cheap, batch-friendly, ~1MB model |
| 4 | LLM router | `gpt-4o-mini` classification call: "which tier: simple / moderate / complex?" | Most accurate, fallback only |
| 5 | Model tiers | **Tier 1**: Ollama local / `gpt-4o-mini` / `claude-haiku`. **Tier 2**: `gpt-4o` / `claude-sonnet`. **Tier 3**: `gpt-4-turbo` / `claude-opus` | Standard 3-tier pricing |
| 6 | Budget enforcement | Per-org daily cap from `settings` (`ai.daily_token_budget`) + per-run cap | Already wired in A |
| 7 | Cost attribution | Already in `token_usage` table + audit log; add `cost_usd` aggregation in usage dashboard | Reuse existing infra |
| 8 | Override | Per-call `tier` kwarg wins over auto-routing; per-org setting `ai.tier_default` sets baseline | Operator control |

---

## DB additions

```sql
-- Routing decision log (for offline analysis)
CREATE TABLE routing_decisions (
  id          BIGSERIAL PRIMARY KEY,
  agent_run_id UUID,
  step_id     UUID,                       -- B sub-system step (nullable)
  prompt_hash VARCHAR(64),                -- SHA256 of normalized prompt
  signals     JSONB,                      -- heuristic + semantic scores
  tier        VARCHAR(16),                -- 1 | 2 | 3
  model       VARCHAR(128),               -- chosen model
  cost_usd    FLOAT,
  decided_by  VARCHAR(16),                -- heuristic | semantic | llm | manual
  created_at  TIMESTAMP DEFAULT now()
);

-- Cost budget alerts
CREATE TABLE budget_alerts (
  id          UUID PRIMARY KEY,
  org_id      UUID,
  kind        VARCHAR(32),                -- daily_50 | daily_90 | daily_100 | per_run_exceeded
  threshold   FLOAT,
  actual      FLOAT,
  period      VARCHAR(32),                -- "2026-07-30"
  created_at  TIMESTAMP DEFAULT now()
);
```

---

## Phases (35 tasks, ~18-25 hours)

### Phase 1 — Heuristic router (Tasks 1-7)
- `HeuristicRouter` class with length/keyword signals
- Configurable per-tier patterns
- Tier assignment table: (min_length, max_length, has_keyword) → tier
- Tests: every tier boundary case

### Phase 2 — Semantic router (Tasks 8-13)
- Bundle sentence-transformers `all-MiniLM-L6-v2` (~80MB, downloaded on first run)
- Build class centroids from a small labeled eval set (simple / moderate / complex prompts)
- Cosine similarity scoring + threshold
- Tests: routing accuracy on the eval set ≥ 85%

### Phase 3 — LLM router fallback (Tasks 14-17)
- `LLMRouter` calls `gpt-4o-mini` (or local equivalent) with a structured prompt
- Response parsed into tier enum
- 5-second timeout; falls back to tier 2 on failure
- Tests: parse valid + invalid LLM responses

### Phase 4 — Composite router (Tasks 18-22)
- `CompositeRouter.tier_for(prompt, context)`: heuristic → semantic → LLM
- Each tier can return "uncertain" to defer to the next
- Logs each decision to `routing_decisions` table
- Cost: heuristic = 0, semantic = 0, LLM = ~$0.0001

### Phase 5 — Model registry (Tasks 23-27)
- `MODEL_TIERS` table in code: per-tier model + pricing + max_tokens
- Per-call override via `LiteLLMClient.completion(tier_override=...)`
- Settings-based override: `ai.tier_default` (org-level)
- Tests: override precedence

### Phase 6 — Budget enforcement + alerts (Tasks 28-32)
- `BudgetEnforcer` extends existing `TokenBudgetEnforcer`
- Daily org budget from settings (`ai.daily_token_budget.<org_id>`)
- Threshold alerts at 50% / 90% / 100%
- Notification on each alert (uses Sub-System C)
- Tests: budget violation path

### Phase 7 — Observability + dashboard (Tasks 33-35)
- Prometheus: `apexai_routing_decisions_total{tier,decided_by}`,
  `apexai_routing_cost_saved_usd_total{tier}`
- Update `/agent/usage/summary` endpoint with cost + savings
- Frontend: cost widget on dashboard

---

## Routing algorithm

```python
def tier_for(prompt: str, context: dict | None = None) -> TierDecision:
    # Tier 1: heuristic
    h = HeuristicRouter().score(prompt)
    if h.confidence >= 0.8:
        return TierDecision(tier=h.tier, decided_by="heuristic", signals=h.signals)

    # Tier 2: semantic
    s = SemanticRouter().score(prompt)
    if s.confidence >= 0.7:
        return TierDecision(tier=s.tier, decided_by="semantic", signals=s.signals)

    # Tier 3: LLM fallback
    try:
        l = LLMRouter().score(prompt, timeout=5.0)
        return TierDecision(tier=l.tier, decided_by="llm", signals=l.signals)
    except Exception:
        # Conservative default: tier 2
        return TierDecision(tier=2, decided_by="manual_fallback", signals={})

    # Else: default
    return TierDecision(tier=2, decided_by="default", signals={})
```

---

## Files

```
backend/app/cost/
├── __init__.py
├── models.py             # RoutingDecision, BudgetAlert
├── tiers.py              # MODEL_TIERS table, Tier enum
├── heuristic.py          # length/keyword signals
├── semantic.py           # sentence-transformers + centroids
├── llm_router.py         # LLM fallback classifier
├── composite.py          # orchestrates the 3 tiers
├── budget.py             # daily cap + alert thresholds
└── api.py                # /cost/* endpoints
```

---

## API surface

```
GET  /cost/usage?org_id=...&period=1d|7d|30d
GET  /cost/by-model?org_id=...&period=7d
GET  /cost/by-tier?org_id=...&period=7d       # how many calls landed in each tier
GET  /cost/decisions?limit=50                # recent routing decisions
POST /cost/budget                           # set per-org daily cap
```

---

## Open items

- LLM router quality depends on labeled eval set — need ~50 hand-labeled prompts to bootstrap
- sentence-transformers model is ~80MB; consider distilling to a smaller model if startup time matters
- Cost data is sensitive — add per-org row-level security (org members see only their org)