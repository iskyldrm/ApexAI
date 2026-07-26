# ApexAI

Multi-tenant AI agent platform.

## Status

- **Sub-System F (Multi-tenant Platform)**: Phases 0-5 done (auth, orgs, teams, invitations, API keys, settings, audit log). 70 backend tests passing.
- **Sub-System G (Frontend)**: Phase 6 done — Next.js 14 + shadcn UI (login, dashboard, orgs, keys, settings, audit).
- **Sub-System A (Agent Runtime)**: Plan written, not yet started.
- **Sub-Systems B, C, D, E**: Plans pending.

## Development

```bash
make dev-infra    # Start PostgreSQL, Redis, Vault in Docker
make backend      # Run FastAPI at :8000
make frontend     # Run Next.js at :3000
make test         # Run all tests
make migrate      # Run Alembic migrations
```

## Architecture

See `docs/superpowers/specs/`:

- F: Multi-tenant Platform (auth, RBAC, key vault, audit) — done
- G: Frontend (Next.js 14 + shadcn) — done
- A: Agent Runtime — in progress
- B: Workflow Orchestration
- C: Task Tracking Dashboard
- D: Cost Optimization
- E: Build/Test Pipeline

## Quick start

```bash
# Backend
cd backend
uv sync
uv run uvicorn app.main:app --reload    # http://localhost:8000

# Frontend
cd frontend
pnpm install
pnpm dev                                # http://localhost:3000
```

## Repo Layout

```
apexai/
├── backend/          # FastAPI + SQLModel + Alembic
├── frontend/         # Next.js 14 + shadcn
├── deploy/           # Helm charts for k8s
├── docs/superpowers/ # Specs + implementation plans
└── scripts/          # Helper scripts
```

## Tech Stack

- **Backend:** Python 3.12, FastAPI 0.115+, SQLModel 0.0.22+, Pydantic v2, Alembic, hvac, bcrypt, PyJWT
- **Frontend:** Next.js 14 (App Router), TypeScript, shadcn/ui, Tailwind, Radix
- **Data:** PostgreSQL 16 (Row-Level Security), Redis 7
- **Secrets:** HashiCorp Vault 1.17+ (KV v2)
- **Infra:** Docker, Helm, Kubernetes, GitHub Actions
