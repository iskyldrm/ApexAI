# ApexAI

Multi-tenant AI agent platform.

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

- F: Multi-tenant Platform (auth, RBAC, key vault, audit)
- A: Agent Runtime (in progress)
- B: Workflow Orchestration
- C: Task Tracking Dashboard
- D: Cost Optimization
- E: Build/Test Pipeline
- G: Full Frontend

## Repo Layout

```
apexai/
├── backend/          # FastAPI + SQLModel + Alembic
├── frontend/         # Next.js 14 + shadcn (in F plan)
├── deploy/           # Helm charts for k8s
├── docs/superpowers/ # Specs + implementation plans
└── scripts/          # Helper scripts
```

## Tech Stack

- **Backend:** Python 3.12, FastAPI 0.115+, SQLModel 0.0.22+, Pydantic v2, Alembic, hvac, bcrypt, PyJWT
- **Frontend:** Next.js 14 (App Router), TypeScript, shadcn/ui, Tailwind, React Query, Zustand
- **Data:** PostgreSQL 16 (Row-Level Security), Redis 7
- **Secrets:** HashiCorp Vault 1.17+ (KV v2)
- **Infra:** Docker, Helm, Kubernetes, GitHub Actions
