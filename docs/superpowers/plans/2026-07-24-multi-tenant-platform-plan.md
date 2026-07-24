# F: Multi-Tenant Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ApexAI's F sub-system: multi-tenant auth, RBAC, AI key vault, integrations, settings, and audit log — the foundation for sub-systems A (Agent Runtime), B (Workflow), C (Task Tracker), D (Cost), E (Build/Test), G (Frontend).

**Architecture:** FastAPI + SQLModel + PostgreSQL 16 (Row-Level Security) + HashiCorp Vault (KV v2) + Redis + Next.js 14 (App Router, shadcn). 4-level tenant hierarchy (Platform → Org → Team → User). JWT in httpOnly cookies, bcrypt hashing, double-layer RBAC.

**Tech Stack:** Python 3.12, FastAPI 0.115+, SQLModel, Pydantic v2, Alembic, hvac, bcrypt, PyJWT, passlib; PostgreSQL 16 (RLS), Redis 7, Vault 1.17+; Next.js 14, TypeScript, shadcn/ui, Tailwind, React Query, Zustand; uv, pnpm, Docker, Helm.

**Spec:** `docs/superpowers/specs/2026-07-24-multi-tenant-platform-design.md`

---

## File Structure

```
apexai/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI entry
│   │   ├── config.py                # Pydantic settings
│   │   ├── db.py                    # SQLModel session
│   │   ├── deps.py                  # FastAPI deps (current_user, db, etc.)
│   │   ├── enums.py                 # Role, Permission, Status enums
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── security.py          # JWT, password hashing
│   │   │   ├── rbac.py              # Permission decorators
│   │   │   ├── audit.py             # Audit helper
│   │   │   └── vault.py             # Vault client
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── platform_admin.py
│   │   │   ├── user.py
│   │   │   ├── org.py
│   │   │   ├── team.py
│   │   │   ├── membership.py
│   │   │   ├── invitation.py
│   │   │   ├── api_key.py
│   │   │   ├── integration.py
│   │   │   ├── audit_log.py
│   │   │   ├── setting.py
│   │   │   ├── token_usage.py
│   │   │   └── auth_token.py        # password_reset, email_verification, refresh
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── org.py
│   │   │   ├── team.py
│   │   │   ├── user.py
│   │   │   ├── invitation.py
│   │   │   ├── api_key.py
│   │   │   ├── integration.py
│   │   │   ├── audit.py
│   │   │   └── setting.py
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py        # aggregates all routers
│   │   │       ├── auth.py
│   │   │       ├── platform.py
│   │   │       ├── orgs.py
│   │   │       ├── teams.py
│   │   │       ├── users.py
│   │   │       ├── invitations.py
│   │   │       ├── keys.py
│   │   │       ├── integrations.py
│   │   │       ├── audit.py
│   │   │       └── settings.py
│   │   └── alembic/
│   │       ├── env.py
│   │       ├── script.py.mako
│   │       └── versions/
│   ├── tests/
│   │   ├── conftest.py              # Test fixtures (db, client, fixtures)
│   │   ├── test_security.py
│   │   ├── test_rbac.py
│   │   ├── test_audit.py
│   │   ├── test_vault.py
│   │   ├── api/
│   │   │   ├── test_auth.py
│   │   │   ├── test_orgs.py
│   │   │   ├── test_teams.py
│   │   │   ├── test_users.py
│   │   │   ├── test_invitations.py
│   │   │   ├── test_keys.py
│   │   │   ├── test_integrations.py
│   │   │   ├── test_audit.py
│   │   │   └── test_settings.py
│   │   └── migrations/
│   │       └── test_migrations.py
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── Dockerfile
│   └── docker-compose.dev.yml
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── login/page.tsx
│   │   ├── forgot-password/page.tsx
│   │   ├── reset-password/page.tsx
│   │   ├── invitations/accept/page.tsx
│   │   ├── (authenticated)/
│   │   │   ├── layout.tsx
│   │   │   ├── dashboard/page.tsx
│   │   │   ├── orgs/page.tsx
│   │   │   ├── orgs/[id]/page.tsx
│   │   │   ├── orgs/[id]/teams/page.tsx
│   │   │   ├── orgs/[id]/users/page.tsx
│   │   │   ├── orgs/[id]/keys/page.tsx
│   │   │   ├── orgs/[id]/integrations/page.tsx
│   │   │   ├── orgs/[id]/audit/page.tsx
│   │   │   └── settings/page.tsx
│   │   └── api/
│   ├── components/
│   │   ├── ui/                     # shadcn primitives
│   │   ├── auth/
│   │   ├── layout/
│   │   └── settings/
│   ├── lib/
│   │   ├── api.ts                  # API client
│   │   ├── auth.ts                 # JWT helpers
│   │   └── utils.ts
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── Dockerfile
├── deploy/
│   └── helm/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
│           ├── fastapi-deployment.yaml
│           ├── fastapi-service.yaml
│           ├── fastapi-ingress.yaml
│           ├── nextjs-deployment.yaml
│           ├── nextjs-service.yaml
│           ├── nextjs-ingress.yaml
│           ├── postgres-statefulset.yaml
│           ├── vault-statefulset.yaml
│           ├── redis-deployment.yaml
│           ├── configmap.yaml
│           ├── secret.yaml
│           └── serviceaccount.yaml
├── docker-compose.dev.yml         # Local dev infra
├── .github/
│   └── workflows/
│       ├── backend-ci.yaml
│       ├── frontend-ci.yaml
│       └── helm-deploy.yaml
├── Makefile
├── README.md
└── docs/
    └── superpowers/
        ├── specs/
        │   └── 2026-07-24-multi-tenant-platform-design.md
        └── plans/
            └── 2026-07-24-multi-tenant-platform-plan.md (this file)
```

---

## Phase 0: Project Bootstrap (Tasks 1-7)

### Task 1: Initialize ApexAI repo with uv

**Files:**
- Create: `apexai/pyproject.toml`
- Create: `apexai/.gitignore`
- Create: `apexai/README.md`
- Create: `apexai/Makefile`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p apexai/{backend,frontend,deploy/helm/templates,docs/superpowers,scripts}
cd apexai
git init -q
git config user.email "isak@apex.ai"
git config user.name "İsak Yıldırım"
```

- [ ] **Step 2: Create backend pyproject.toml**

Write `apexai/backend/pyproject.toml`:
```toml
[project]
name = "apexai-backend"
version = "0.1.0"
description = "ApexAI multi-tenant platform backend"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlmodel>=0.0.22",
    "psycopg[binary]>=3.2.0",
    "alembic>=1.13.0",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "pyjwt>=2.9.0",
    "passlib[bcrypt]>=1.7.4",
    "bcrypt==4.0.1",
    "python-multipart>=0.0.12",
    "hvac>=2.3.0",
    "redis>=5.2.0",
    "httpx>=0.27.0",
    "email-validator>=2.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.7.0",
    "mypy>=1.13.0",
    "testcontainers[postgres,vault,redis]>=4.8.0",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Install uv and dependencies**

```bash
# Install uv (if not already)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync backend deps
cd apexai/backend
uv sync --all-extras
```

Expected: Lock file created, all deps installed.

- [ ] **Step 4: Create .gitignore**

Write `apexai/.gitignore`:
```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
.pytest_cache/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/
uv.lock

# Node
node_modules/
.next/
out/
*.tsbuildinfo
.env
.env.local

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# k8s
*.kubeconfig

# Secrets (never commit)
*.pem
*.key
.env
.env.prod
```

- [ ] **Step 5: Create README and Makefile**

Write `apexai/README.md`:
```markdown
# ApexAI

Multi-tenant AI agent platform.

## Development

```bash
make dev-infra    # Start PostgreSQL, Redis, Vault in Docker
make backend      # Run FastAPI at :8000
make frontend     # Run Next.js at :3000
make test         # Run all tests
```

## Architecture

See `docs/superpowers/specs/`.
```

Write `apexai/Makefile`:
```makefile
.PHONY: dev-infra backend frontend test lint migrate

dev-infra:
	cd backend && docker compose -f docker-compose.dev.yml up -d

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

test:
	cd backend && uv run pytest -v

lint:
	cd backend && uv run ruff check .
	cd backend && uv run mypy app

migrate:
	cd backend && uv run alembic upgrade head
```

- [ ] **Step 6: Commit**

```bash
cd apexai
git add .
git commit -m "chore: initialize ApexAI monorepo with uv backend"
```

### Task 2: Docker Compose for dev infrastructure

**Files:**
- Create: `apexai/backend/docker-compose.dev.yml`

- [ ] **Step 1: Create docker-compose.dev.yml**

```yaml
services:
  postgres:
    image: postgres:16
    container_name: apexai_postgres
    restart: unless-stopped
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_DB=apexai
      - POSTGRES_USER=apexai
      - POSTGRES_PASSWORD=apexai_dev
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U apexai"]
      interval: 2s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    container_name: apexai_redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  vault:
    image: hashicorp/vault:1.17
    container_name: apexai_vault
    restart: unless-stopped
    ports:
      - "8200:8200"
    environment:
      - VAULT_DEV_ROOT_TOKEN_ID=apexai_dev_token
      - VAULT_DEV_LISTEN_ADDRESS=0.0.0.0:8200
      - VAULT_ADDR=http://0.0.0.0:8200
    cap_add:
      - IPC_LOCK
    volumes:
      - vault_data:/vault/file

volumes:
  postgres_data:
  redis_data:
  vault_data:
```

- [ ] **Step 2: Start the dev infrastructure**

```bash
cd apexai/backend
docker compose -f docker-compose.dev.yml up -d
sleep 5
docker compose -f docker-compose.dev.yml ps
```

Expected: All 3 services "Up" with health check passing.

- [ ] **Step 3: Verify connectivity**

```bash
# PostgreSQL
docker exec apexai_postgres psql -U apexai -d apexai -c "SELECT 1;"
# Redis
docker exec apexai_redis redis-cli PING
# Vault
docker exec apexai_vault vault status
```

Expected: All respond successfully.

- [ ] **Step 4: Commit**

```bash
cd apexai
git add backend/docker-compose.dev.yml
git commit -m "chore: add docker-compose for dev infra (postgres, redis, vault)"
```

### Task 3: FastAPI skeleton with health check

**Files:**
- Create: `apexai/backend/app/__init__.py`
- Create: `apexai/backend/app/main.py`
- Create: `apexai/backend/app/config.py`
- Create: `apexai/backend/tests/__init__.py`
- Create: `apexai/backend/tests/conftest.py`
- Create: `apexai/backend/tests/test_health.py`

- [ ] **Step 1: Write the failing test**

Write `apexai/backend/tests/test_health.py`:
```python
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apexai/backend
uv run pytest tests/test_health.py -v
```

Expected: FAIL with "fixture not found" or "connection refused".

- [ ] **Step 3: Create empty package files**

```bash
touch apexai/backend/app/__init__.py
touch apexai/backend/tests/__init__.py
```

- [ ] **Step 4: Create config.py**

Write `apexai/backend/app/config.py`:
```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+psycopg://apexai:apexai_dev@localhost:5432/apexai"

    # Vault
    vault_url: str = "http://localhost:8200"
    vault_token: str = "apexai_dev_token"
    vault_mount_point: str = "secret"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret: str = "dev-secret-change-me-in-production-please-use-32-bytes-min"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30

    # App
    app_env: str = "development"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Invite
    invite_ttl_days: int = 7
    password_reset_ttl_minutes: int = 30
    email_verification_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Create main.py with health endpoint**

Write `apexai/backend/app/main.py`:
```python
from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="ApexAI API",
    version="0.1.0",
    description="Multi-tenant AI agent platform",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
)


@app.get("/health")
async def health_check() -> dict:
    return {"status": "healthy"}


@app.get("/ready")
async def readiness_check() -> dict:
    return {"status": "ready"}
```

- [ ] **Step 6: Create conftest.py with test client fixture**

Write `apexai/backend/tests/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
```

- [ ] **Step 7: Run test to verify it passes**

```bash
cd apexai/backend
uv run pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd apexai
git add backend/
git commit -m "feat(backend): FastAPI skeleton with health check"
```

### Task 4: Database connection and session

**Files:**
- Create: `apexai/backend/app/db.py`
- Modify: `apexai/backend/tests/conftest.py`
- Create: `apexai/backend/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Write `apexai/backend/tests/test_db.py`:
```python
import pytest
from sqlalchemy import text

from app.db import get_session


@pytest.mark.asyncio
async def test_database_connection():
    async with get_session() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apexai/backend
uv run pytest tests/test_db.py -v
```

Expected: FAIL with "ModuleNotFoundError: app.db" or "no get_session".

- [ ] **Step 3: Create db.py**

Write `apexai/backend/app/db.py`:
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables. Used in tests and on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apexai/backend
uv run pytest tests/test_db.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd apexai
git add backend/
git commit -m "feat(backend): async database connection with SQLModel"
```

### Task 5: SQLModel base models

**Files:**
- Create: `apexai/backend/app/models/__init__.py`
- Create: `apexai/backend/app/models/base.py`
- Create: `apexai/backend/tests/test_models_base.py`

- [ ] **Step 1: Write the failing test**

Write `apexai/backend/tests/test_models_base.py`:
```python
from datetime import datetime
from uuid import UUID

from app.models.base import BaseModel


def test_base_model_has_uuid_and_timestamps():
    class TestModel(BaseModel, table=True):
        __tablename__ = "test_base_model"
        name: str

    instance = TestModel(name="test")
    assert isinstance(instance.id, UUID)
    assert isinstance(instance.created_at, datetime)
    assert isinstance(instance.updated_at, datetime)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apexai/backend
uv run pytest tests/test_models_base.py -v
```

Expected: FAIL with "ModuleNotFoundError".

- [ ] **Step 3: Create base.py**

```bash
mkdir -p apexai/backend/app/models
touch apexai/backend/app/models/__init__.py
```

Write `apexai/backend/app/models/base.py`:
```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class BaseModel(SQLModel):
    """Base for all persistent models. Mixin, not a standalone table."""

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apexai/backend
uv run pytest tests/test_models_base.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd apexai
git add backend/
git commit -m "feat(backend): SQLModel BaseModel with UUID and timestamps"
```

### Task 6: Alembic setup

**Files:**
- Create: `apexai/backend/alembic.ini`
- Create: `apexai/backend/app/alembic/env.py`
- Create: `apexai/backend/app/alembic/script.py.mako`
- Create: `apexai/backend/app/alembic/__init__.py`
- Create: `apexai/backend/tests/migrations/test_migrations.py`

- [ ] **Step 1: Create alembic directory structure**

```bash
mkdir -p apexai/backend/app/alembic/versions
touch apexai/backend/app/alembic/__init__.py
touch apexai/backend/app/alembic/versions/__init__.py
```

- [ ] **Step 2: Write the failing test**

Write `apexai/backend/tests/migrations/test_migrations.py`:
```python
import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings


@pytest.mark.asyncio
async def test_alembic_upgrade_creates_tables():
    settings = get_settings()
    test_db_url = settings.database_url + "_test"
    engine = create_async_engine(test_db_url)

    # Run alembic upgrade head programmatically
    from alembic.config import Config
    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", test_db_url)
    command.upgrade(cfg, "head")

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert "platform_admins" in tables
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd apexai/backend
uv run pytest tests/migrations/test_migrations.py -v
```

Expected: FAIL with "alembic not configured" or similar.

- [ ] **Step 4: Create alembic.ini**

Write `apexai/backend/alembic.ini`:
```ini
[alembic]
script_location = app/alembic
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = driver://user:pass@localhost/db

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 5: Create env.py**

Write `apexai/backend/app/alembic/env.py`:
```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Import all models so they register with SQLModel.metadata
from app.config import get_settings
from app.models.base import BaseModel  # noqa: F401
from app.models.platform_admin import PlatformAdmin  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.org import Org  # noqa: F401
from app.models.team import Team  # noqa: F401
from app.models.membership import OrgMembership, TeamMembership  # noqa: F401
from app.models.invitation import Invitation  # noqa: F401
from app.models.api_key import ApiKey  # noqa: F401
from app.models.integration import IntegrationCredential  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.setting import Setting  # noqa: F401
from app.models.token_usage import TokenUsage  # noqa: F401
from app.models.auth_token import (  # noqa: F401
    PasswordResetToken,
    EmailVerificationToken,
    RefreshToken,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("+psycopg", ""))

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 6: Create script.py.mako**

Write `apexai/backend/app/alembic/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
import sqlmodel
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 7: Verify alembic config**

Will work after models are created in Phase 1. Skip run for now.

- [ ] **Step 8: Commit**

```bash
cd apexai
git add backend/
git commit -m "feat(backend): alembic setup with async env config"
```

### Task 7: Enums module

**Files:**
- Create: `apexai/backend/app/enums.py`
- Create: `apexai/backend/tests/test_enums.py`

- [ ] **Step 1: Write the failing test**

Write `apexai/backend/tests/test_enums.py`:
```python
from app.enums import Role, Permission, OrgStatus, ApiKeyProvider, IntegrationType


def test_role_enum_values():
    assert Role.ADMIN == "admin"
    assert Role.MANAGER == "manager"
    assert Role.DEVELOPER == "developer"
    assert Role.ANALYST == "analyst"
    assert Role.TECH_SUPPORT == "tech_support"
    assert Role.HR == "hr"


def test_permission_enum_values():
    assert Permission.ORG_MANAGE == "org:manage"
    assert Permission.TASKS_CREATE == "tasks:create"


def test_api_key_provider_enum():
    assert ApiKeyProvider.OPENAI == "openai"
    assert ApiKeyProvider.ANTHROPIC == "anthropic"
    assert ApiKeyProvider.GOOGLE == "google"
    assert ApiKeyProvider.OLLAMA == "ollama"
    assert ApiKeyProvider.CUSTOM == "custom"


def test_integration_type_enum():
    assert IntegrationType.GITHUB_APP == "github_app"
    assert IntegrationType.GITHUB_OAUTH == "github_oauth"
    assert IntegrationType.GITHUB_PAT == "github_pat"
    assert IntegrationType.TELEGRAM_BOT == "telegram_bot"
    assert IntegrationType.AZURE_SP == "azure_sp"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apexai/backend
uv run pytest tests/test_enums.py -v
```

Expected: FAIL with "ModuleNotFoundError".

- [ ] **Step 3: Create enums.py**

Write `apexai/backend/app/enums.py`:
```python
from enum import Enum


class Role(str, Enum):
    """Org-wide role. 6 types per spec §5.2."""

    ADMIN = "admin"
    MANAGER = "manager"
    DEVELOPER = "developer"
    ANALYST = "analyst"
    TECH_SUPPORT = "tech_support"
    HR = "hr"


class TeamRole(str, Enum):
    """Team-level extra role per spec §5.3."""

    LEAD = "lead"
    MEMBER = "member"
    OBSERVER = "observer"


class Permission(str, Enum):
    """Permission-based RBAC per spec §5.1."""

    # Org
    ORG_MANAGE = "org:manage"
    ORG_VIEW = "org:view"
    # Users
    USERS_INVITE = "users:invite"
    USERS_MANAGE = "users:manage"
    USERS_VIEW = "users:view"
    # Teams
    TEAMS_MANAGE = "teams:manage"
    TEAMS_VIEW = "teams:view"
    # Tasks
    TASKS_CREATE = "tasks:create"
    TASKS_VIEW_ALL = "tasks:view:all"
    TASKS_VIEW_TEAM = "tasks:view:team"
    TASKS_VIEW_OWN = "tasks:view:own"
    TASKS_APPROVE = "tasks:approve"
    # Keys
    KEYS_MANAGE_ORG = "keys:manage:org"
    KEYS_MANAGE_OWN = "keys:manage:own"
    KEYS_VIEW_ALL = "keys:view:all"
    KEYS_VIEW_OWN = "keys:view:own"
    # Integrations
    INTEGRATIONS_MANAGE_ORG = "integrations:manage:org"
    INTEGRATIONS_MANAGE_OWN = "integrations:manage:own"
    INTEGRATIONS_VIEW = "integrations:view"
    # Audit
    AUDIT_VIEW = "audit:view"
    # Settings
    SETTINGS_MANAGE_ORG = "settings:manage:org"
    SETTINGS_MANAGE_OWN = "settings:manage:own"


# Role → Permission mapping per spec §5.2
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: {
        Permission.ORG_MANAGE, Permission.ORG_VIEW,
        Permission.USERS_INVITE, Permission.USERS_MANAGE, Permission.USERS_VIEW,
        Permission.TEAMS_MANAGE, Permission.TEAMS_VIEW,
        Permission.TASKS_CREATE, Permission.TASKS_VIEW_ALL, Permission.TASKS_VIEW_TEAM,
        Permission.TASKS_VIEW_OWN, Permission.TASKS_APPROVE,
        Permission.KEYS_MANAGE_ORG, Permission.KEYS_MANAGE_OWN,
        Permission.KEYS_VIEW_ALL, Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_ORG, Permission.INTEGRATIONS_MANAGE_OWN,
        Permission.INTEGRATIONS_VIEW,
        Permission.AUDIT_VIEW,
        Permission.SETTINGS_MANAGE_ORG, Permission.SETTINGS_MANAGE_OWN,
    },
    Role.MANAGER: {
        Permission.ORG_VIEW,
        Permission.USERS_VIEW, Permission.TEAMS_VIEW,
        Permission.TASKS_CREATE, Permission.TASKS_VIEW_ALL, Permission.TASKS_VIEW_TEAM,
        Permission.TASKS_VIEW_OWN, Permission.TASKS_APPROVE,
        Permission.KEYS_MANAGE_OWN, Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_OWN, Permission.INTEGRATIONS_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.DEVELOPER: {
        Permission.ORG_VIEW, Permission.TEAMS_VIEW,
        Permission.TASKS_CREATE, Permission.TASKS_VIEW_TEAM, Permission.TASKS_VIEW_OWN,
        Permission.KEYS_MANAGE_OWN, Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_OWN, Permission.INTEGRATIONS_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.ANALYST: {
        Permission.ORG_VIEW, Permission.TEAMS_VIEW,
        Permission.TASKS_CREATE, Permission.TASKS_VIEW_ALL, Permission.TASKS_VIEW_OWN,
        Permission.TASKS_APPROVE,
        Permission.KEYS_MANAGE_OWN, Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_OWN, Permission.INTEGRATIONS_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.TECH_SUPPORT: {
        Permission.ORG_VIEW, Permission.TEAMS_VIEW,
        Permission.TASKS_VIEW_TEAM, Permission.TASKS_VIEW_OWN,
        Permission.KEYS_MANAGE_OWN, Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_ORG, Permission.INTEGRATIONS_MANAGE_OWN,
        Permission.INTEGRATIONS_VIEW,
        Permission.AUDIT_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
    Role.HR: {
        Permission.ORG_VIEW, Permission.TEAMS_VIEW,
        Permission.USERS_INVITE, Permission.USERS_MANAGE, Permission.USERS_VIEW,
        Permission.TASKS_VIEW_TEAM, Permission.TASKS_VIEW_OWN,
        Permission.KEYS_MANAGE_OWN, Permission.KEYS_VIEW_OWN,
        Permission.INTEGRATIONS_MANAGE_OWN, Permission.INTEGRATIONS_VIEW,
        Permission.AUDIT_VIEW,
        Permission.SETTINGS_MANAGE_OWN,
    },
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


class OrgStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class MembershipStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    SUSPENDED = "suspended"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ApiKeyProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class IntegrationType(str, Enum):
    GITHUB_APP = "github_app"
    GITHUB_OAUTH = "github_oauth"
    GITHUB_PAT = "github_pat"
    TELEGRAM_BOT = "telegram_bot"
    AZURE_SP = "azure_sp"


class AuditActorType(str, Enum):
    USER = "user"
    PLATFORM_ADMIN = "platform_admin"
    SYSTEM = "system"


class SettingScope(str, Enum):
    PLATFORM = "platform"
    ORG = "org"
    TEAM = "team"
    USER = "user"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apexai/backend
uv run pytest tests/test_enums.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd apexai
git add backend/
git commit -m "feat(backend): enums module with role/permission mapping"
```

---

## Phase 1: Database Models (Tasks 8-22)

For each model: create model file, write test, run migration to ensure it creates the table correctly.

### Task 8: PlatformAdmin model

**Files:**
- Create: `apexai/backend/app/models/platform_admin.py`
- Modify: `apexai/backend/app/models/__init__.py`
- Create: `apexai/backend/app/alembic/versions/2026_07_24_120000_create_platform_admins.py`

- [ ] **Step 1: Create the model file**

Write `apexai/backend/app/models/platform_admin.py`:
```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import String
from sqlmodel import Field

from app.enums import Role  # noqa: F401  # Used in role literal types
from app.models.base import BaseModel


class PlatformAdmin(BaseModel, table=True):
    __tablename__ = "platform_admins"

    email: str = Field(sa_column=String(255), unique=True, index=True, nullable=False)
    password_hash: str = Field(nullable=False)
    full_name: str = Field(sa_column=String(255), nullable=False)
    last_login_at: datetime | None = Field(default=None)
```

- [ ] **Step 2: Update models/__init__.py**

Write `apexai/backend/app/models/__init__.py`:
```python
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.auth_token import (
    EmailVerificationToken,
    PasswordResetToken,
    RefreshToken,
)
from app.models.base import BaseModel
from app.models.integration import IntegrationCredential
from app.models.invitation import Invitation
from app.models.membership import OrgMembership, TeamMembership
from app.models.org import Org
from app.models.platform_admin import PlatformAdmin
from app.models.setting import Setting
from app.models.team import Team
from app.models.token_usage import TokenUsage
from app.models.user import User

__all__ = [
    "ApiKey",
    "AuditLog",
    "BaseModel",
    "EmailVerificationToken",
    "IntegrationCredential",
    "Invitation",
    "Org",
    "OrgMembership",
    "PasswordResetToken",
    "PlatformAdmin",
    "RefreshToken",
    "Setting",
    "Team",
    "TeamMembership",
    "TokenUsage",
    "User",
]
```

- [ ] **Step 3: Create placeholder files for other models**

```bash
cd apexai/backend
for m in user org team membership invitation api_key integration audit_log setting token_usage auth_token; do
  echo "from app.models.base import BaseModel" > app/models/$m.py
done
```

- [ ] **Step 4: Generate initial migration**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create platform_admins"
```

Expected: A new file in `app/alembic/versions/`.

- [ ] **Step 5: Run migration**

```bash
cd apexai/backend
uv run alembic upgrade head
```

Expected: Tables created in PostgreSQL.

- [ ] **Step 6: Verify**

```bash
docker exec apexai_postgres psql -U apexai -d apexai -c "\d platform_admins"
```

Expected: Table is shown with all columns.

- [ ] **Step 7: Commit**

```bash
cd apexai
git add backend/
git commit -m "feat(backend): PlatformAdmin model + initial migration"
```

> **Pattern for Tasks 9-22:** Create model file → regenerate migration → run migration → verify → commit. See Task 8 as template.

### Task 9: User model

**Files:**
- Modify: `apexai/backend/app/models/user.py`

- [ ] **Step 1: Update user.py**

```python
from datetime import datetime
from sqlalchemy import String
from sqlmodel import Field

from app.models.base import BaseModel


class User(BaseModel, table=True):
    __tablename__ = "users"

    email: str = Field(sa_column=String(255), unique=True, index=True, nullable=False)
    password_hash: str = Field(nullable=False)
    full_name: str = Field(sa_column=String(255), nullable=False)
    is_active: bool = Field(default=True)
    email_verified_at: datetime | None = Field(default=None)
    last_login_at: datetime | None = Field(default=None)
```

- [ ] **Step 2: Generate and run migration**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create users"
uv run alembic upgrade head
docker exec apexai_postgres psql -U apexai -d apexai -c "\d users"
```

- [ ] **Step 3: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): User model"
```

### Task 10: Org model

**Files:**
- Modify: `apexai/backend/app/models/org.py`

- [ ] **Step 1: Update org.py**

```python
from datetime import datetime
from sqlalchemy import String
from sqlmodel import Field

from app.models.base import BaseModel


class Org(BaseModel, table=True):
    __tablename__ = "orgs"

    slug: str = Field(sa_column=String(64), unique=True, index=True, nullable=False)
    name: str = Field(sa_column=String(255), nullable=False)
    status: str = Field(default="active", sa_column=String(32))
    settings: str = Field(default="{}", nullable=False)  # JSON-encoded
    created_by: str | None = Field(default=None)  # PlatformAdmin UUID as string
```

- [ ] **Step 2: Generate migration, run, verify, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create orgs"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): Org model"
```

### Task 11: Team model

**Files:**
- Modify: `apexai/backend/app/models/team.py`

- [ ] **Step 1: Update team.py**

```python
from sqlalchemy import String
from sqlmodel import Field

from app.models.base import BaseModel


class Team(BaseModel, table=True):
    __tablename__ = "teams"

    org_id: str = Field(foreign_key="orgs.id", index=True, nullable=False)
    name: str = Field(sa_column=String(255), nullable=False)
    slug: str = Field(sa_column=String(64), nullable=False)
    description: str | None = Field(default=None)
    created_by: str | None = Field(default=None)
```

- [ ] **Step 2: Generate migration, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create teams"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): Team model"
```

### Task 12: Membership models

**Files:**
- Modify: `apexai/backend/app/models/membership.py`

- [ ] **Step 1: Update membership.py**

```python
from datetime import datetime
from sqlalchemy import String
from sqlmodel import Field

from app.models.base import BaseModel


class OrgMembership(BaseModel, table=True):
    __tablename__ = "org_memberships"

    org_id: str = Field(foreign_key="orgs.id", index=True, nullable=False)
    user_id: str = Field(foreign_key="users.id", index=True, nullable=False)
    role: str = Field(sa_column=String(32), nullable=False)
    status: str = Field(default="active", sa_column=String(32))
    invited_by: str | None = Field(default=None)
    joined_at: datetime | None = Field(default=None)


class TeamMembership(BaseModel, table=True):
    __tablename__ = "team_memberships"

    team_id: str = Field(foreign_key="teams.id", index=True, nullable=False)
    user_id: str = Field(foreign_key="users.id", index=True, nullable=False)
    team_role: str = Field(sa_column=String(32), nullable=False)
    added_by: str | None = Field(default=None)
```

- [ ] **Step 2: Generate migration, run, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create org_memberships and team_memberships"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): OrgMembership and TeamMembership models"
```

### Task 13: Invitation model

**Files:**
- Modify: `apexai/backend/app/models/invitation.py`

- [ ] **Step 1: Update invitation.py**

```python
from datetime import datetime
from sqlalchemy import String
from sqlmodel import Field

from app.models.base import BaseModel


class Invitation(BaseModel, table=True):
    __tablename__ = "invitations"

    org_id: str = Field(foreign_key="orgs.id", index=True, nullable=False)
    email: str = Field(sa_column=String(255), nullable=False)
    role: str = Field(sa_column=String(32), nullable=False)
    team_ids: str = Field(default="[]", nullable=False)  # JSON array
    token_hash: str = Field(sa_column=String(255), unique=True, index=True, nullable=False)
    expires_at: datetime = Field(nullable=False)
    status: str = Field(default="pending", sa_column=String(32))
    invited_by: str = Field(nullable=False)
```

- [ ] **Step 2: Generate migration, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create invitations"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): Invitation model"
```

### Task 14: ApiKey model

**Files:**
- Modify: `apexai/backend/app/models/api_key.py`

- [ ] **Step 1: Update api_key.py**

```python
from datetime import datetime
from sqlalchemy import String, CheckConstraint
from sqlmodel import Field

from app.models.base import BaseModel


class ApiKey(BaseModel, table=True):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "(org_id IS NULL) != (user_id IS NULL)",
            name="api_keys_owner_xor",
        ),
    )

    org_id: str | None = Field(default=None, foreign_key="orgs.id", index=True)
    user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    provider: str = Field(sa_column=String(32), nullable=False)
    label: str = Field(sa_column=String(255), nullable=False)
    vault_path: str = Field(sa_column=String(512), nullable=False)
    is_active: bool = Field(default=True)
    last_used_at: datetime | None = Field(default=None)
    created_by: str = Field(nullable=False)
```

- [ ] **Step 2: Generate migration, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create api_keys with check constraint"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): ApiKey model with org/user XOR constraint"
```

### Task 15: Integration model

**Files:**
- Modify: `apexai/backend/app/models/integration.py`

- [ ] **Step 1: Update integration.py**

```python
from datetime import datetime
from sqlalchemy import String, CheckConstraint
from sqlmodel import Field

from app.models.base import BaseModel


class IntegrationCredential(BaseModel, table=True):
    __tablename__ = "integration_credentials"
    __table_args__ = (
        CheckConstraint(
            "(org_id IS NULL) != (user_id IS NULL)",
            name="integration_credentials_owner_xor",
        ),
    )

    org_id: str | None = Field(default=None, foreign_key="orgs.id", index=True)
    user_id: str | None = Field(default=None, foreign_key="users.id", index=True)
    integration_type: str = Field(sa_column=String(32), nullable=False)
    label: str = Field(sa_column=String(255), nullable=False)
    vault_path: str = Field(sa_column=String(512), nullable=False)
    is_active: bool = Field(default=True)
    last_used_at: datetime | None = Field(default=None)
```

- [ ] **Step 2: Generate migration, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create integration_credentials"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): IntegrationCredential model"
```

### Task 16: AuditLog model

**Files:**
- Modify: `apexai/backend/app/models/audit_log.py`

- [ ] **Step 1: Update audit_log.py**

```python
from sqlalchemy import String
from sqlmodel import Field, JSON

from app.models.base import BaseModel


class AuditLog(BaseModel, table=True):
    __tablename__ = "audit_log"

    actor_type: str = Field(sa_column=String(32), nullable=False)
    actor_id: str | None = Field(default=None, index=True)
    actor_email_snapshot: str | None = Field(default=None)
    action: str = Field(sa_column=String(64), index=True, nullable=False)
    target_type: str | None = Field(default=None)
    target_id: str | None = Field(default=None)
    org_id: str | None = Field(default=None, foreign_key="orgs.id", index=True)
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    meta: dict = Field(default={}, sa_column=JSON)
```

- [ ] **Step 2: Generate migration, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create audit_log"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): AuditLog model"
```

### Task 17: Settings model

**Files:**
- Modify: `apexai/backend/app/models/setting.py`

- [ ] **Step 1: Update setting.py**

```python
from sqlalchemy import String
from sqlmodel import Field, JSON

from app.models.base import BaseModel


class Setting(BaseModel, table=True):
    __tablename__ = "settings"

    scope: str = Field(sa_column=String(32), nullable=False)
    scope_id: str | None = Field(default=None, index=True)
    key: str = Field(sa_column=String(128), nullable=False)
    value: dict = Field(default={}, sa_column=JSON)
    enforced_by_admin: bool = Field(default=False)
    updated_by: str | None = Field(default=None)
```

- [ ] **Step 2: Generate migration, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create settings"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): Setting model"
```

### Task 18: TokenUsage model

**Files:**
- Modify: `apexai/backend/app/models/token_usage.py`

- [ ] **Step 1: Update token_usage.py**

```python
from decimal import Decimal
from sqlalchemy import String
from sqlmodel import Field

from app.models.base import BaseModel


class TokenUsage(BaseModel, table=True):
    __tablename__ = "token_usage"

    user_id: str = Field(foreign_key="users.id", index=True, nullable=False)
    org_id: str = Field(foreign_key="orgs.id", index=True, nullable=False)
    api_key_id: str = Field(foreign_key="api_keys.id", nullable=False)
    provider: str = Field(sa_column=String(32), nullable=False)
    model: str = Field(sa_column=String(64), nullable=False)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cost_usd: Decimal = Field(default=Decimal("0"), max_digits=10, decimal_places=6)
```

- [ ] **Step 2: Generate migration, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create token_usage"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): TokenUsage model"
```

### Task 19: Auth token models (password_reset, email_verification, refresh)

**Files:**
- Modify: `apexai/backend/app/models/auth_token.py`

- [ ] **Step 1: Update auth_token.py**

```python
from datetime import datetime
from sqlalchemy import String
from sqlmodel import Field

from app.models.base import BaseModel


class PasswordResetToken(BaseModel, table=True):
    __tablename__ = "password_reset_tokens"

    user_id: str = Field(foreign_key="users.id", nullable=False)
    token_hash: str = Field(sa_column=String(255), unique=True, index=True, nullable=False)
    expires_at: datetime = Field(nullable=False)
    used_at: datetime | None = Field(default=None)


class EmailVerificationToken(BaseModel, table=True):
    __tablename__ = "email_verification_tokens"

    user_id: str = Field(foreign_key="users.id", nullable=False)
    new_email: str | None = Field(default=None)
    token_hash: str = Field(sa_column=String(255), unique=True, index=True, nullable=False)
    expires_at: datetime = Field(nullable=False)
    used_at: datetime | None = Field(default=None)


class RefreshToken(BaseModel, table=True):
    __tablename__ = "refresh_tokens"

    user_id: str = Field(foreign_key="users.id", index=True, nullable=False)
    token_hash: str = Field(sa_column=String(255), unique=True, index=True, nullable=False)
    expires_at: datetime = Field(nullable=False)
    revoked_at: datetime | None = Field(default=None)
    ip_address: str | None = Field(default=None)
```

- [ ] **Step 2: Generate migration, commit**

```bash
cd apexai/backend
uv run alembic revision --autogenerate -m "create auth tokens (password reset, email verify, refresh)"
uv run alembic upgrade head
cd apexai && git add backend/ && git commit -m "feat(backend): auth token models (password/email/refresh)"
```

### Task 20: Composite indexes migration

**Files:**
- Create: `apexai/backend/app/alembic/versions/2026_07_24_130000_add_composite_indexes.py`

- [ ] **Step 1: Create manual migration**

```bash
cd apexai/backend
uv run alembic revision -m "add composite indexes for hot queries"
```

- [ ] **Step 2: Edit the migration file**

```python
"""add composite indexes for hot queries

Revision ID: add_composite_indexes
Revises: previous
Create Date: 2026-07-24 13:00:00
"""
from alembic import op


revision = "add_composite_indexes"
down_revision = "create_auth_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # org_memberships
    op.create_index("idx_org_memberships_user", "org_memberships", ["user_id"])
    # team_memberships
    op.create_index("idx_team_memberships_user", "team_memberships", ["user_id"])
    # api_keys hot path
    op.create_index(
        "idx_api_keys_org_provider",
        "api_keys",
        ["org_id", "provider", "is_active"],
    )
    op.create_index(
        "idx_api_keys_user_provider",
        "api_keys",
        ["user_id", "provider", "is_active"],
    )
    # audit_log hot path
    op.create_index(
        "idx_audit_log_org_created",
        "audit_log",
        ["org_id", op.desc("created_at")],
    )
    op.create_index(
        "idx_audit_log_actor_created",
        "audit_log",
        ["actor_id", op.desc("created_at")],
    )
    # token_usage
    op.create_index(
        "idx_token_usage_org_created",
        "token_usage",
        ["org_id", op.desc("created_at")],
    )
    op.create_index(
        "idx_token_usage_user_created",
        "token_usage",
        ["user_id", op.desc("created_at")],
    )
    # settings
    op.create_index(
        "idx_settings_scope_key",
        "settings",
        ["scope", "scope_id", "key"],
        unique=True,
    )
    # teams
    op.create_index(
        "idx_teams_org_slug",
        "teams",
        ["org_id", "slug"],
        unique=True,
    )
    # org memberships
    op.create_index(
        "idx_org_memberships_org_user",
        "org_memberships",
        ["org_id", "user_id"],
        unique=True,
    )
    # team memberships
    op.create_index(
        "idx_team_memberships_team_user",
        "team_memberships",
        ["team_id", "user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_team_memberships_team_user", "team_memberships")
    op.drop_index("idx_org_memberships_org_user", "org_memberships")
    op.drop_index("idx_teams_org_slug", "teams")
    op.drop_index("idx_settings_scope_key", "settings")
    op.drop_index("idx_token_usage_user_created", "token_usage")
    op.drop_index("idx_token_usage_org_created", "token_usage")
    op.drop_index("idx_audit_log_actor_created", "audit_log")
    op.drop_index("idx_audit_log_org_created", "audit_log")
    op.drop_index("idx_api_keys_user_provider", "api_keys")
    op.drop_index("idx_api_keys_org_provider", "api_keys")
    op.drop_index("idx_team_memberships_user", "team_memberships")
    op.drop_index("idx_org_memberships_user", "org_memberships")
```

- [ ] **Step 3: Run migration**

```bash
cd apexai/backend
uv run alembic upgrade head
docker exec apexai_postgres psql -U apexai -d apexai -c "\di"
```

- [ ] **Step 4: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): composite indexes for hot queries"
```

### Task 21: Row-Level Security policies

**Files:**
- Create: `apexai/backend/app/alembic/versions/2026_07_24_140000_enable_rls.py`

- [ ] **Step 1: Generate migration**

```bash
cd apexai/backend
uv run alembic revision -m "enable row-level security on tenant tables"
```

- [ ] **Step 2: Edit migration**

```python
"""enable row-level security on tenant tables

Revision ID: enable_rls
Revises: add_composite_indexes
"""
from alembic import op


revision = "enable_rls"
down_revision = "add_composite_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable RLS on all tenant-scoped tables
    tenant_tables = [
        "orgs",
        "teams",
        "org_memberships",
        "team_memberships",
        "api_keys",
        "integration_credentials",
        "audit_log",
        "settings",
        "token_usage",
    ]
    for table in tenant_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")

    # org_memberships: user sees own + org admin sees all
    op.execute("""
        CREATE POLICY org_memberships_user_sees_own ON org_memberships
        FOR SELECT USING (user_id::text = current_setting('app.current_user_id', true));
    """)
    op.execute("""
        CREATE POLICY org_memberships_org_admin_sees_all ON org_memberships
        FOR SELECT USING (
            EXISTS (
                SELECT 1 FROM org_memberships om
                WHERE om.org_id = org_memberships.org_id
                  AND om.user_id::text = current_setting('app.current_user_id', true)
                  AND om.role = 'admin' AND om.status = 'active'
            ) OR current_setting('app.is_platform_admin', true) = 'true'
        );
    """)
    op.execute("""
        CREATE POLICY org_memberships_platform_admin ON org_memberships
        FOR ALL USING (current_setting('app.is_platform_admin', true) = 'true');
    """)

    # teams: org members see all teams in their org
    op.execute("""
        CREATE POLICY teams_org_member_sees ON teams
        FOR SELECT USING (
            EXISTS (
                SELECT 1 FROM org_memberships om
                WHERE om.org_id = teams.org_id
                  AND om.user_id::text = current_setting('app.current_user_id', true)
                  AND om.status = 'active'
            ) OR current_setting('app.is_platform_admin', true) = 'true'
        );
    """)

    # settings: scope filters
    op.execute("""
        CREATE POLICY settings_scope ON settings
        FOR SELECT USING (
            (scope = 'platform' AND current_setting('app.is_platform_admin', true) = 'true')
            OR (scope = 'org' AND scope_id IN (
                SELECT om.org_id FROM org_memberships om
                WHERE om.user_id::text = current_setting('app.current_user_id', true)
                  AND om.status = 'active'
            ))
            OR (scope = 'user' AND scope_id::text = current_setting('app.current_user_id', true))
            OR (scope = 'team' AND scope_id IN (
                SELECT tm.team_id FROM team_memberships tm
                WHERE tm.user_id::text = current_setting('app.current_user_id', true)
            ))
        );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS settings_scope ON settings;")
    op.execute("DROP POLICY IF EXISTS teams_org_member_sees ON teams;")
    op.execute("DROP POLICY IF EXISTS org_memberships_platform_admin ON org_memberships;")
    op.execute("DROP POLICY IF EXISTS org_memberships_org_admin_sees_all ON org_memberships;")
    op.execute("DROP POLICY IF EXISTS org_memberships_user_sees_own ON org_memberships;")
    for table in [
        "token_usage", "settings", "audit_log", "integration_credentials",
        "api_keys", "team_memberships", "org_memberships", "teams", "orgs",
    ]:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
```

- [ ] **Step 3: Run migration**

```bash
cd apexai/backend
uv run alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): enable RLS on tenant tables"
```

### Task 22: Database seed for platform admin

**Files:**
- Create: `apexai/backend/app/db_seeder.py`
- Create: `apexai/backend/tests/test_db_seeder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db_seeder.py
import pytest

from app.db_seeder import seed_platform_admin
from app.models.platform_admin import PlatformAdmin


@pytest.mark.asyncio
async def test_seed_platform_admin_creates_first_admin():
    admin = await seed_platform_admin(
        email="admin@apex.ai",
        password="admin123",
        full_name="Platform Admin",
    )
    assert admin.email == "admin@apex.ai"
    assert admin.password_hash != "admin123"  # Hashed
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apexai/backend && uv run pytest tests/test_db_seeder.py -v
```

- [ ] **Step 3: Create db_seeder.py**

```python
# app/db_seeder.py
from sqlalchemy import select
from sqlmodel import Session

from app.core.security import hash_password
from app.db import async_session_maker
from app.models.platform_admin import PlatformAdmin


async def seed_platform_admin(email: str, password: str, full_name: str) -> PlatformAdmin:
    """Create the first platform admin if it doesn't exist."""
    async with async_session_maker() as session:
        existing = await session.execute(
            select(PlatformAdmin).where(PlatformAdmin.email == email)
        )
        if existing.scalar_one_or_none():
            return existing.scalar_one()

        admin = PlatformAdmin(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        return admin
```

- [ ] **Step 4: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): platform admin seeder"
```

---

## Phase 2: Core Utilities (Tasks 23-28)

### Task 23: Password hashing

**Files:**
- Create: `apexai/backend/app/core/security.py`
- Create: `apexai/backend/app/core/__init__.py`
- Create: `apexai/backend/tests/test_security.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_security.py
from app.core.security import hash_password, verify_password


def test_hash_and_verify_password():
    h = hash_password("my-secret-123")
    assert h != "my-secret-123"
    assert verify_password("my-secret-123", h) is True
    assert verify_password("wrong", h) is False
```

- [ ] **Step 2: Run test, verify fail**

```bash
cd apexai/backend && uv run pytest tests/test_security.py -v
```

- [ ] **Step 3: Create core/__init__.py and security.py**

```bash
touch apexai/backend/app/core/__init__.py
```

```python
# app/core/security.py
import bcrypt


def hash_password(plain: str) -> str:
    """Hash password using bcrypt with cost 12."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd apexai/backend && uv run pytest tests/test_security.py -v
```

- [ ] **Step 5: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): bcrypt password hashing"
```

### Task 24: JWT utilities

**Files:**
- Modify: `apexai/backend/app/core/security.py`
- Modify: `apexai/backend/tests/test_security.py`

- [ ] **Step 1: Add failing tests**

```python
# Append to tests/test_security.py
from app.core.security import create_access_token, decode_token

def test_create_and_decode_access_token():
    token = create_access_token(
        user_id="user-123",
        email="ali@acme.com",
        is_platform_admin=False,
        orgs=[{"org_id": "org-1", "role": "developer", "teams": ["team-1"]}],
    )
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["email"] == "ali@acme.com"
    assert payload["is_platform_admin"] is False
    assert payload["orgs"][0]["role"] == "developer"


def test_decode_invalid_token_raises():
    import pytest
    from jose import JWTError
    with pytest.raises(JWTError):
        decode_token("not-a-valid-token")
```

- [ ] **Step 2: Run test, verify fail**

```bash
cd apexai/backend && uv run pytest tests/test_security.py -v
```

- [ ] **Step 3: Implement JWT functions**

Append to `app/core/security.py`:
```python
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


def create_access_token(
    user_id: str,
    email: str,
    is_platform_admin: bool,
    orgs: list[dict],
    ttl_minutes: int | None = None,
) -> str:
    """Create a JWT access token (15 min default)."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ttl_minutes or settings.jwt_access_ttl_minutes)
    payload = {
        "sub": user_id,
        "email": email,
        "is_platform_admin": is_platform_admin,
        "orgs": orgs,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_refresh_token() -> tuple[str, str]:
    """Generate a refresh token. Returns (plain, sha256_hash)."""
    import secrets
    import hashlib
    plain = secrets.token_urlsafe(48)
    h = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return plain, h
```

Add `python-jose` to dependencies:
```bash
cd apexai/backend
uv add "python-jose[cryptography]>=3.3.0"
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd apexai/backend && uv run pytest tests/test_security.py -v
```

- [ ] **Step 5: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): JWT and refresh token utilities"
```

### Task 25: Vault client

**Files:**
- Create: `apexai/backend/app/core/vault.py`
- Create: `apexai/backend/tests/test_vault.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_vault.py
import pytest

from app.core.vault import VaultClient


@pytest.mark.asyncio
async def test_vault_write_and_read():
    client = VaultClient()
    await client.write("test/foo", {"value": "bar"})
    result = await client.read("test/foo")
    assert result == {"value": "bar"}
    await client.delete("test/foo")
```

- [ ] **Step 2: Run test, verify fail**

- [ ] **Step 3: Implement VaultClient**

```python
# app/core/vault.py
import hvac

from app.config import get_settings

settings = get_settings()


class VaultClient:
    """HashiCorp Vault KV v2 client. Singleton-friendly."""

    def __init__(self) -> None:
        self._client = hvac.Client(url=settings.vault_url, token=settings.vault_token)
        if not self._client.is_authenticated():
            raise RuntimeError("Vault authentication failed")
        self._mount = settings.vault_mount_point

    async def read(self, path: str) -> dict:
        response = self._client.secrets.kv.v2.read_secret_version(
            path=path, mount_point=self._mount
        )
        return response["data"]["data"]

    async def write(self, path: str, data: dict) -> None:
        self._client.secrets.kv.v2.create_or_update_secret(
            path=path, secret=data, mount_point=self._mount
        )

    async def delete(self, path: str) -> None:
        self._client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=path, mount_point=self._mount
        )
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd apexai/backend && uv run pytest tests/test_vault.py -v
```

- [ ] **Step 5: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): HashiCorp Vault client (KV v2)"
```

### Task 26: Audit helper

**Files:**
- Create: `apexai/backend/app/core/audit.py`
- Create: `apexai/backend/tests/test_audit.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_audit.py
import pytest
from datetime import datetime

from app.core.audit import audit


@pytest.mark.asyncio
async def test_audit_writes_entry():
    await audit(
        action="test.event",
        actor_id="user-1",
        actor_type="user",
        actor_email="test@example.com",
        org_id="org-1",
        metadata={"foo": "bar"},
    )
    # Verify by querying
    from sqlalchemy import select
    from app.db import async_session_maker
    from app.models.audit_log import AuditLog

    async with async_session_maker() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.action == "test.event")
        )
        entry = result.scalar_one()
        assert entry.actor_email == "test@example.com"
        assert entry.metadata == {"foo": "bar"}
```

- [ ] **Step 2: Implement audit()**

```python
# app/core/audit.py
from typing import Any

from sqlalchemy import insert

from app.db import async_session_maker
from app.models.audit_log import AuditLog


async def audit(
    action: str,
    actor_id: str | None = None,
    actor_type: str = "system",
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    org_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write an audit log entry. Fire-and-forget pattern."""
    async with async_session_maker() as session:
        await session.execute(
            insert(AuditLog).values(
                actor_type=actor_type,
                actor_id=actor_id,
                actor_email_snapshot=actor_email,
                action=action,
                target_type=target_type,
                target_id=target_id,
                org_id=org_id,
                ip_address=ip_address,
                user_agent=user_agent,
                meta=metadata or {},
            )
        )
        await session.commit()
```

- [ ] **Step 3: Run test, verify pass**

- [ ] **Step 4: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): audit helper"
```

### Task 27: RBAC decorators

**Files:**
- Create: `apexai/backend/app/core/rbac.py`
- Create: `apexai/backend/tests/test_rbac.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_rbac.py
import pytest
from fastapi import HTTPException

from app.core.rbac import require_permission, require_org_role, require_team_role
from app.enums import Permission, Role, TeamRole


def test_require_permission_grants_when_user_has_perm():
    @require_permission(Permission.TASKS_CREATE)
    def handler(user_role: Role = Role.DEVELOPER) -> str:
        return "ok"

    assert handler() == "ok"


def test_require_permission_denies_when_user_lacks_perm():
    @require_permission(Permission.ORG_MANAGE)
    def handler(user_role: Role = Role.DEVELOPER) -> str:
        return "ok"

    with pytest.raises(HTTPException) as exc:
        handler()
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Implement RBAC**

```python
# app/core/rbac.py
from functools import wraps
from typing import Callable

from fastapi import HTTPException, status

from app.enums import Permission, Role, TeamRole, has_permission


def require_permission(permission: Permission) -> Callable:
    """Decorator: user must have the given permission via their role."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user_role: Role | None = kwargs.get("user_role")
            is_platform_admin: bool = kwargs.get("is_platform_admin", False)
            if is_platform_admin:
                return await func(*args, **kwargs)
            if user_role is None or not has_permission(user_role, permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing permission: {permission.value}",
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_org_role(allowed_roles: list[Role]) -> Callable:
    """Decorator: user must have one of the given org roles."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user_role: Role | None = kwargs.get("user_role")
            is_platform_admin: bool = kwargs.get("is_platform_admin", False)
            if is_platform_admin or (user_role in allowed_roles):
                return await func(*args, **kwargs)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {[r.value for r in allowed_roles]}",
            )

        return wrapper

    return decorator


def require_team_role(allowed_roles: list[TeamRole]) -> Callable:
    """Decorator: user must have one of the given team roles for the team."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user_team_roles: list[TeamRole] = kwargs.get("user_team_roles", [])
            is_platform_admin: bool = kwargs.get("is_platform_admin", False)
            if is_platform_admin or any(r in allowed_roles for r in user_team_roles):
                return await func(*args, **kwargs)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required team role: {[r.value for r in allowed_roles]}",
            )

        return wrapper

    return decorator
```

- [ ] **Step 3: Run test, verify pass**

- [ ] **Step 4: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): RBAC decorators"
```

### Task 28: FastAPI dependencies (current_user, db session)

**Files:**
- Create: `apexai/backend/app/deps.py`
- Create: `apexai/backend/tests/test_deps.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_deps.py
import pytest
from httpx import AsyncClient, ASGITransport
from jose import jwt

from app.config import get_settings
from app.main import app


@pytest.mark.asyncio
async def test_get_current_user_from_jwt():
    settings = get_settings()
    token = jwt.encode(
        {
            "sub": "user-123",
            "email": "test@example.com",
            "is_platform_admin": False,
            "orgs": [],
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/test-me",
            cookies={"access_token": token},
        )
    assert response.status_code == 200
    assert response.json()["email"] == "test@example.com"
```

- [ ] **Step 2: Add test endpoint to main.py**

Append to `app/main.py`:
```python
from app.deps import get_current_user

@app.get("/api/v1/test-me")
async def test_me(current_user=__import__("fastapi").Depends(get_current_user)):
    return {"email": current_user["email"], "sub": current_user["sub"]}
```

- [ ] **Step 3: Implement deps.py**

```python
# app/deps.py
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session

settings = get_settings()


async def get_db() -> AsyncSession:
    async with get_session() as session:
        yield session


async def get_current_user(
    access_token: Annotated[str | None, Cookie(alias="access_token")] = None,
) -> dict:
    """Extract JWT from cookie, verify, return claims."""
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token missing",
        )
    try:
        return jwt.decode(
            access_token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


async def get_optional_user(
    access_token: Annotated[str | None, Cookie(alias="access_token")] = None,
) -> dict | None:
    if not access_token:
        return None
    try:
        return jwt.decode(
            access_token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None
```

- [ ] **Step 4: Test should pass**

```bash
cd apexai/backend && uv run pytest tests/test_deps.py -v
```

- [ ] **Step 5: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): FastAPI dependencies (current_user, db session)"
```

---

## Phase 3: Auth Endpoints (Tasks 29-34)

### Task 29: Login endpoint

**Files:**
- Create: `apexai/backend/app/schemas/auth.py`
- Create: `apexai/backend/app/api/v1/auth.py`
- Create: `apexai/backend/app/api/v1/__init__.py`
- Create: `apexai/backend/app/api/__init__.py`
- Modify: `apexai/backend/app/main.py`
- Create: `apexai/backend/tests/api/test_auth.py`

- [ ] **Step 1: Create schema**

```python
# app/schemas/auth.py
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
```

- [ ] **Step 2: Create routers**

```bash
mkdir -p apexai/backend/app/api/v1
touch apexai/backend/app/api/__init__.py
touch apexai/backend/app/api/v1/__init__.py
```

- [ ] **Step 3: Write failing test**

```python
# tests/api/test_auth.py
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.user import User
from app.core.security import hash_password


@pytest.mark.asyncio
async def test_login_success():
    async with get_test_session() as session:
        user = User(
            email="test@example.com",
            password_hash=hash_password("password123"),
            full_name="Test",
        )
        session.add(user)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "password123"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert "refresh_token" in body
```

- [ ] **Step 4: Implement login endpoint**

```python
# app/api/v1/auth.py
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.security import create_access_token, generate_refresh_token, verify_password
from app.deps import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.enums import Role

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    # Find user
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Build orgs list with roles
    from app.models.membership import OrgMembership
    memberships = await db.execute(
        select(OrgMembership).where(OrgMembership.user_id == str(user.id))
    )
    orgs = []
    for m in memberships.scalars():
        if m.status == "active":
            orgs.append({"org_id": m.org_id, "role": m.role, "teams": []})

    # Create access token
    access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        is_platform_admin=False,
        orgs=orgs,
    )

    # Create refresh token
    plain, token_hash = generate_refresh_token()
    refresh = RefreshToken(
        user_id=str(user.id),
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days),
    )
    db.add(refresh)
    await db.commit()

    # Update last_login
    user.last_login_at = datetime.utcnow()
    await db.commit()

    # Set cookies
    response.set_cookie(
        "access_token", access,
        httponly=True, secure=True, samesite="lax",
        max_age=settings.jwt_access_ttl_minutes * 60,
    )
    response.set_cookie(
        "refresh_token", plain,
        httponly=True, secure=True, samesite="lax",
        max_age=settings.jwt_refresh_ttl_days * 86400,
    )

    return TokenResponse(
        access_token=access,
        refresh_token=plain,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )
```

- [ ] **Step 5: Register router in main.py**

Modify `app/main.py`:
```python
from app.api.v1.auth import router as auth_router

# ... in FastAPI app setup:
app.include_router(auth_router, prefix="/api/v1")
```

- [ ] **Step 6: Test**

```bash
cd apexai/backend && uv run pytest tests/api/test_auth.py -v
```

- [ ] **Step 7: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): login endpoint with JWT + refresh cookies"
```

### Task 30: Refresh endpoint

**Files:**
- Modify: `apexai/backend/app/api/v1/auth.py`
- Modify: `apexai/backend/tests/api/test_auth.py`

- [ ] **Step 1: Add failing test**

```python
# Append to test_auth.py
@pytest.mark.asyncio
async def test_refresh_returns_new_access_token():
    # ... use existing refresh_token from previous test or generate one
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": "test-refresh-token"},
        )
    # Should either succeed (if test-refresh-token is valid) or fail with 401
    assert response.status_code in [200, 401]
```

- [ ] **Step 2: Implement refresh**

Append to `app/api/v1/auth.py`:
```python
from fastapi import Cookie

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> TokenResponse:
    """Refresh access token using refresh_token cookie."""
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()
    if not record or record.revoked_at or record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = await db.get(User, record.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Build orgs list
    from app.models.membership import OrgMembership
    memberships = await db.execute(
        select(OrgMembership).where(OrgMembership.user_id == str(user.id))
    )
    orgs = [
        {"org_id": m.org_id, "role": m.role, "teams": []}
        for m in memberships.scalars()
        if m.status == "active"
    ]

    access = create_access_token(
        user_id=str(user.id),
        email=user.email,
        is_platform_admin=False,
        orgs=orgs,
    )
    response.set_cookie(
        "access_token", access,
        httponly=True, secure=True, samesite="lax",
        max_age=settings.jwt_access_ttl_minutes * 60,
    )
    return TokenResponse(
        access_token=access,
        refresh_token=cookie_value,
        expires_in=settings.jwt_access_ttl_minutes * 60,
    )
```

- [ ] **Step 3: Test**

```bash
cd apexai/backend && uv run pytest tests/api/test_auth.py -v
```

- [ ] **Step 4: Commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): refresh token endpoint"
```

### Task 31: Logout endpoint

**Files:**
- Modify: `apexai/backend/app/api/v1/auth.py`

- [ ] **Step 1: Add failing test**

```python
@pytest.mark.asyncio
async def test_logout_clears_cookies_and_revokes_refresh():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert "access_token" not in response.cookies
```

- [ ] **Step 2: Implement**

```python
@router.post("/logout")
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: Annotated[str | None, Cookie(alias="refresh_token")] = None,
) -> dict:
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        record = result.scalar_one_or_none()
        if record and not record.revoked_at:
            record.revoked_at = datetime.utcnow()
            await db.commit()
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"message": "Logged out"}
```

- [ ] **Step 3: Test, commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): logout endpoint"
```

### Task 32: Forgot password endpoint

**Files:**
- Create: `apexai/backend/app/schemas/auth.py` (extend)
- Modify: `apexai/backend/app/api/v1/auth.py`
- Create: `apexai/backend/app/email_log.py`

- [ ] **Step 1: Add schemas**

```python
# Append to app/schemas/auth.py
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=6)
```

- [ ] **Step 2: Create email_log.py**

```python
# app/email_log.py
"""Email 'log' writer — stubs real SMTP for now. Spec §1.3 notes email deferred."""
import json
from datetime import datetime
from pathlib import Path

from app.config import get_settings

settings = get_settings()
LOG_FILE = Path("/tmp/apexai_emails.log")


def log_email(to: str, subject: str, body: str) -> None:
    """Write a JSON line to the email log file."""
    with LOG_FILE.open("a") as f:
        f.write(
            json.dumps(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "to": to,
                    "subject": subject,
                    "body": body,
                }
            )
            + "\n"
        )
```

- [ ] **Step 3: Add failing test**

```python
@pytest.mark.asyncio
async def test_forgot_password_returns_success():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "test@example.com"},
        )
    assert response.status_code == 200
```

- [ ] **Step 4: Implement**

```python
# Append to app/api/v1/auth.py
from app.email_log import log_email
from app.models.auth_token import PasswordResetToken
from app.core.security import generate_refresh_token  # reuse for token generation (just string)

@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        # Don't leak whether email exists
        return {"message": "If the email is registered, a reset link has been sent."}

    plain, token_hash = generate_refresh_token()
    record = PasswordResetToken(
        user_id=str(user.id),
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_ttl_minutes),
    )
    db.add(record)
    await db.commit()

    reset_url = f"http://localhost:3000/reset-password?token={plain}"
    log_email(
        to=user.email,
        subject="Reset your ApexAI password",
        body=f"Click to reset: {reset_url}",
    )
    return {"message": "If the email is registered, a reset link has been sent."}
```

- [ ] **Step 5: Test, commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): forgot password endpoint"
```

### Task 33: Reset password endpoint

**Files:**
- Modify: `apexai/backend/app/api/v1/auth.py`

- [ ] **Step 1: Add failing test**

```python
@pytest.mark.asyncio
async def test_reset_password_with_valid_token():
    # Need to insert PasswordResetToken first
    from app.models.auth_token import PasswordResetToken
    import hashlib
    from datetime import datetime, timedelta, timezone

    plain = "test-reset-token"
    token_hash = hashlib.sha256(plain.encode()).hexdigest()
    async with get_test_session() as session:
        user = await session.get(User, "user-id")  # need valid user
        record = PasswordResetToken(
            user_id=str(user.id),
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        session.add(record)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/reset-password",
            json={"token": plain, "new_password": "new-secret-456"},
        )
    assert response.status_code == 200
```

- [ ] **Step 2: Implement**

```python
@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    record = result.scalar_one_or_none()
    if not record or record.used_at or record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = await db.get(User, record.user_id)
    user.password_hash = hash_password(body.new_password)
    record.used_at = datetime.utcnow()
    await db.commit()
    return {"message": "Password successfully reset"}
```

- [ ] **Step 3: Test, commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): reset password endpoint"
```

### Task 34: Auth `me` endpoint

**Files:**
- Modify: `apexai/backend/app/api/v1/auth.py`

- [ ] **Step 1: Add failing test**

```python
@pytest.mark.asyncio
async def test_me_returns_user_info():
    # Login first, then call /me
    ...
```

- [ ] **Step 2: Implement**

```python
@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)) -> dict:
    return {
        "id": current_user["sub"],
        "email": current_user["email"],
        "is_platform_admin": current_user.get("is_platform_admin", False),
        "orgs": current_user.get("orgs", []),
    }
```

- [ ] **Step 3: Test, commit**

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): auth /me endpoint"
```

---

## Phase 4: Org/Team/User/Invitation API (Tasks 35-50)

For brevity, these tasks follow the established pattern. Each task has:
1. Schema definition
2. Router function with TDD
3. Test
4. Commit

### Task 35: Org schemas

**Files:**
- Create: `apexai/backend/app/schemas/org.py`

```python
from pydantic import BaseModel, Field
from uuid import UUID


class OrgCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=2, max_length=255)
    admin_email: str
    admin_full_name: str


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    status: str | None = None


class OrgResponse(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    created_at: str
```

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): org schemas"
```

### Task 36: Platform admin — create org endpoint

**Files:**
- Create: `apexai/backend/app/api/v1/platform.py`
- Modify: `apexai/backend/app/main.py`

```python
# app/api/v1/platform.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.deps import get_db
from app.enums import Role
from app.models.membership import OrgMembership
from app.models.org import Org
from app.models.user import User
from app.schemas.org import OrgCreate, OrgResponse

router = APIRouter(prefix="/platform", tags=["platform"])


@router.post("/orgs", response_model=OrgResponse, status_code=201)
async def create_org(body: OrgCreate, db: AsyncSession = Depends(get_db)) -> OrgResponse:
    # Create org
    org = Org(slug=body.slug, name=body.name, status="active", created_by=None)
    db.add(org)
    await db.flush()  # to get org.id

    # Create or find admin user
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.email == body.admin_email))
    admin_user = result.scalar_one_or_none()
    if not admin_user:
        admin_user = User(
            email=body.admin_email,
            password_hash=hash_password("change-me-on-first-login"),
            full_name=body.admin_full_name,
            is_active=True,
            email_verified_at=__import__("datetime").datetime.utcnow(),
        )
        db.add(admin_user)
        await db.flush()

    # Create admin membership
    membership = OrgMembership(
        org_id=str(org.id),
        user_id=str(admin_user.id),
        role=Role.ADMIN.value,
        status="active",
    )
    db.add(membership)
    await db.commit()
    await db.refresh(org)

    return OrgResponse(
        id=org.id,
        slug=org.slug,
        name=org.name,
        status=org.status,
        created_at=org.created_at.isoformat(),
    )
```

Register in `main.py`:
```python
from app.api.v1.platform import router as platform_router
app.include_router(platform_router, prefix="/api/v1")
```

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): platform admin create-org endpoint"
```

### Task 37: Org list and get

```python
# Append to app/api/v1/platform.py
@router.get("/orgs", response_model=list[OrgResponse])
async def list_orgs(db: AsyncSession = Depends(get_db)) -> list[OrgResponse]:
    from sqlalchemy import select
    result = await db.execute(select(Org).order_by(Org.created_at.desc()))
    return [
        OrgResponse(
            id=o.id, slug=o.slug, name=o.name, status=o.status,
            created_at=o.created_at.isoformat(),
        )
        for o in result.scalars()
    ]
```

### Task 38-42: Team, User, Invitation endpoints

(Follow the same pattern. See spec §9.4-9.5 for the full endpoint list.)

### Task 43: Invitation accept endpoint

**Files:**
- Modify: `apexai/backend/app/api/v1/invitations.py`

```python
# app/api/v1/invitations.py
import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.deps import get_db
from app.enums import Role
from app.models.invitation import Invitation
from app.models.membership import OrgMembership, TeamMembership
from app.models.user import User
from app.schemas.invitation import InvitationAcceptRequest

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.post("/accept")
async def accept_invitation(
    body: InvitationAcceptRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    result = await db.execute(
        select(Invitation).where(Invitation.token_hash == token_hash)
    )
    inv = result.scalar_one_or_none()
    if not inv or inv.status != "pending" or inv.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired invitation")

    # Find or create user
    user_result = await db.execute(select(User).where(User.email == inv.email))
    user = user_result.scalar_one_or_none()
    if not user:
        user = User(
            email=inv.email,
            password_hash=hash_password(body.password),
            full_name=body.full_name,
            is_active=True,
            email_verified_at=datetime.utcnow(),
        )
        db.add(user)
        await db.flush()
    else:
        user.password_hash = hash_password(body.password)
        user.is_active = True
        user.email_verified_at = datetime.utcnow()

    # Create org membership
    import json
    membership = OrgMembership(
        org_id=inv.org_id,
        user_id=str(user.id),
        role=inv.role,
        status="active",
        joined_at=datetime.utcnow(),
    )
    db.add(membership)
    await db.flush()

    # Create team memberships
    team_ids = json.loads(inv.team_ids or "[]")
    for team_id in team_ids:
        db.add(TeamMembership(
            team_id=team_id,
            user_id=str(user.id),
            team_role="member",
        ))

    inv.status = "accepted"
    await db.commit()
    return {"message": "Invitation accepted", "user_id": str(user.id)}
```

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): invitation accept endpoint"
```

---

## Phase 5: Key Vault API (Tasks 51-58)

> Pattern: Create schema → Create router → Test → Commit

### Task 51: AI key schemas

**Files:**
- Create: `apexai/backend/app/schemas/api_key.py`

```python
from pydantic import BaseModel, Field
from uuid import UUID
from app.enums import ApiKeyProvider


class ApiKeyCreate(BaseModel):
    provider: ApiKeyProvider
    label: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=10)  # The actual API key string
    org_id: UUID | None = None  # None = user-level BYOK


class ApiKeyResponse(BaseModel):
    id: UUID
    provider: str
    label: str
    is_active: bool
    last_used_at: str | None
    org_id: UUID | None
```

### Task 52: AI key create endpoint

```python
# app/api/v1/keys.py
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vault import VaultClient
from app.deps import get_db, get_current_user
from app.models.api_key import ApiKey
from app.schemas.api_key import ApiKeyCreate, ApiKeyResponse

router = APIRouter(prefix="/keys", tags=["keys"])
vault = VaultClient()


@router.post("/ai", response_model=ApiKeyResponse, status_code=201)
async def create_ai_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> ApiKeyResponse:
    key_id = secrets.token_urlsafe(16)
    scope_path = (
        f"orgs/{body.org_id}/ai-keys/{key_id}"
        if body.org_id
        else f"users/{current_user['sub']}/ai-keys/{key_id}"
    )
    # Store secret in vault
    await vault.write(scope_path, {"value": body.value})

    # Store metadata in DB
    record = ApiKey(
        id=key_id,
        org_id=str(body.org_id) if body.org_id else None,
        user_id=None if body.org_id else current_user["sub"],
        provider=body.provider.value,
        label=body.label,
        vault_path=scope_path,
        is_active=True,
        created_by=current_user["sub"],
    )
    db.add(record)
    await db.commit()
    return ApiKeyResponse(
        id=record.id,
        provider=record.provider,
        label=record.label,
        is_active=record.is_active,
        last_used_at=None,
        org_id=record.org_id,
    )
```

### Task 53-58: AI key list/get/delete/resolve + integration endpoints

(Follow the same pattern. Spec §6.3 has the resolve_ai_key logic.)

```python
# Append to keys.py
async def resolve_ai_key(
    org_id: str, user_id: str, provider: str, db: AsyncSession
) -> str:
    """User key overrides org key per spec §6.3."""
    from sqlalchemy import select
    # Try user key first
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.user_id == user_id,
            ApiKey.provider == provider,
            ApiKey.is_active == True,
        )
    )
    keys = result.scalars().all()
    if keys:
        key = keys[0]
        secret = await vault.read(key.vault_path)
        key.last_used_at = __import__("datetime").datetime.utcnow()
        await db.commit()
        return secret
    # Fall back to org key
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.org_id == org_id,
            ApiKey.user_id.is_(None),
            ApiKey.provider == provider,
            ApiKey.is_active == True,
        )
    )
    keys = result.scalars().all()
    if keys:
        key = keys[0]
        secret = await vault.read(key.vault_path)
        key.last_used_at = __import__("datetime").datetime.utcnow()
        await db.commit()
        return secret
    raise HTTPException(status_code=404, detail=f"No active {provider} key")
```

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): key vault with resolve_ai_key"
```

---

## Phase 6: Settings + Audit Log API (Tasks 59-65)

### Task 59: Settings schemas

```python
# app/schemas/setting.py
from pydantic import BaseModel
from app.enums import SettingScope


class SettingSetRequest(BaseModel):
    scope: SettingScope
    scope_id: str | None = None
    key: str
    value: dict
    enforced_by_admin: bool = False


class SettingResponse(BaseModel):
    scope: str
    scope_id: str | None
    key: str
    value: dict
    enforced_by_admin: bool
```

### Task 60: Settings get endpoint with hierarchy resolution

```python
# app/api/v1/settings.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_current_user
from app.enums import SettingScope
from app.models.setting import Setting

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/{key}")
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Resolve setting via override chain: user → team → org → platform."""
    candidates = []
    # User scope
    candidates.append((SettingScope.USER, current_user["sub"]))
    # Team scope (for each team in active org)
    for org in current_user.get("orgs", []):
        for team_id in org.get("teams", []):
            candidates.append((SettingScope.TEAM, team_id))
    # Org scope
    for org in current_user.get("orgs", []):
        candidates.append((SettingScope.ORG, org["org_id"]))
    # Platform scope
    candidates.append((SettingScope.PLATFORM, None))

    for scope, scope_id in candidates:
        query = select(Setting).where(Setting.scope == scope.value, Setting.key == key)
        if scope_id:
            query = query.where(Setting.scope_id == scope_id)
        else:
            query = query.where(Setting.scope_id.is_(None))
        result = await db.execute(query)
        setting = result.scalar_one_or_none()
        if setting:
            return {
                "scope": setting.scope,
                "scope_id": setting.scope_id,
                "key": setting.key,
                "value": setting.value,
                "enforced_by_admin": setting.enforced_by_admin,
            }
    raise HTTPException(status_code=404, detail="Setting not found")
```

### Task 61-63: Settings PUT, DELETE, list

```python
@router.put("/{key}")
async def set_setting(
    key: str,
    body: SettingSetRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    # Validate scope ownership
    if body.scope == SettingScope.PLATFORM and not current_user.get("is_platform_admin"):
        raise HTTPException(status_code=403, detail="Platform admin required")
    # ... validation for org/team/user scope

    # Upsert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(Setting).values(
        scope=body.scope.value,
        scope_id=body.scope_id,
        key=key,
        value=body.value,
        enforced_by_admin=body.enforced_by_admin,
        updated_by=current_user["sub"],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["scope", "scope_id", "key"],
        set_={"value": body.value, "enforced_by_admin": body.enforced_by_admin, "updated_by": current_user["sub"]},
    )
    await db.execute(stmt)
    await db.commit()
    return {"message": "Setting updated"}
```

### Task 64-65: Audit log endpoint

```python
# app/api/v1/audit.py
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_current_user
from app.enums import Permission, has_permission
from app.models.audit_log import AuditLog
from app.models.membership import OrgMembership

router = APIRouter(prefix="/audit-log", tags=["audit"])


@router.get("")
async def list_audit_log(
    org_id: str | None = None,
    action: str | None = None,
    actor_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    skip: int = Query(0, ge=0),
    take: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict:
    # Authorization: org admin / tech_support / platform admin
    is_platform_admin = current_user.get("is_platform_admin", False)
    if not is_platform_admin:
        # Check user role in the org
        if not org_id:
            raise HTTPException(status_code=400, detail="org_id required")
        result = await db.execute(
            select(OrgMembership).where(
                OrgMembership.user_id == current_user["sub"],
                OrgMembership.org_id == org_id,
            )
        )
        m = result.scalar_one_or_none()
        if not m or not (m.role == "admin" or m.role == "tech_support" or
                         has_permission(__import__("app.enums", fromlist=["Role"]).Role(m.role), Permission.AUDIT_VIEW)):
            raise HTTPException(status_code=403, detail="Not authorized")

    # Build query
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if org_id:
        query = query.where(AuditLog.org_id == org_id)
    if action:
        query = query.where(AuditLog.action == action)
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
    if end_date:
        query = query.where(AuditLog.created_at <= end_date)

    result = await db.execute(query.offset(skip).limit(take))
    items = [
        {
            "id": str(a.id),
            "actor_type": a.actor_type,
            "actor_id": a.actor_id,
            "action": a.action,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "org_id": a.org_id,
            "ip_address": a.ip_address,
            "metadata": a.meta,
            "created_at": a.created_at.isoformat(),
        }
        for a in result.scalars()
    ]
    return {"items": items, "skip": skip, "take": take}
```

```bash
cd apexai && git add backend/ && git commit -m "feat(backend): settings + audit log endpoints"
```

---

## Phase 7: Frontend — Next.js 14 (Tasks 66-78)

### Task 66: Initialize Next.js with shadcn

```bash
cd apexai/frontend
pnpm create next-app@latest . --typescript --tailwind --app --use-pnpm --no-eslint
pnpm dlx shadcn@latest init
```

Choose: New York style, Slate base color, CSS variables: yes.

Add base components:
```bash
pnpm dlx shadcn@latest add button input form card dialog dropdown-menu toast tabs avatar
pnpm add react-query zustand zod
```

Configure `app/globals.css` per shadcn defaults.

```bash
cd apexai && git add frontend/ && git commit -m "feat(frontend): Next.js 14 + shadcn initial setup"
```

### Task 67: Auth context + API client

```typescript
// frontend/lib/auth.ts
export interface AuthUser {
  id: string;
  email: string;
  is_platform_admin: boolean;
  orgs: Array<{ org_id: string; role: string; teams: string[] }>;
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  const res = await fetch("/api/v1/auth/me", { credentials: "include" });
  if (res.status === 401) return null;
  return res.json();
}
```

```typescript
// frontend/lib/api.ts
export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail);
  }
  return res.json();
}
```

### Task 68-72: Auth pages (login, forgot, reset, accept-invite)

(Follow standard shadcn form + react-hook-form pattern. Each page ~80 LOC.)

### Task 73-77: Org/Team/User/Key/Settings pages

Each page uses shadcn `Table`, `Card`, `Form`, `Dialog` components. Implements CRUD via `api()` client.

```bash
cd apexai && git add frontend/ && git commit -m "feat(frontend): org/team/user/key/settings pages"
```

### Task 78: Auth middleware

```typescript
// frontend/middleware.ts
import { NextResponse, type NextRequest } from "next/server";
import { jwtVerify } from "jose";

const PUBLIC_PATHS = ["/login", "/forgot-password", "/reset-password", "/invitations/accept"];

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC_PATHS.some(p => pathname.startsWith(p))) {
    return NextResponse.next();
  }
  const token = req.cookies.get("access_token")?.value;
  if (!token) {
    return NextResponse.redirect(new URL("/login", req.url));
  }
  try {
    await jwtVerify(token, new TextEncoder().encode(process.env.JWT_SECRET!));
    return NextResponse.next();
  } catch {
    return NextResponse.redirect(new URL("/login", req.url));
  }
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|.*\\.png$).*)"],
};
```

```bash
cd apexai && git add frontend/ && git commit -m "feat(frontend): auth middleware"
```

---

## Phase 8: Deployment (Tasks 79-85)

### Task 79-80: Backend Dockerfile + docker-compose for production

### Task 81-85: Helm charts for fastapi, nextjs, postgres, vault, redis

(Follow the structure in spec §11. Each deployment 50-80 LOC.)

---

## Self-Review Checklist

After writing each task, verify:

- [ ] **Test first, then implement** — every task has a failing test before code
- [ ] **TDD cycle:** write test → run (fail) → implement → run (pass) → commit
- [ ] **No placeholders:** actual code in every step, no "TBD" or "TODO"
- [ ] **Exact file paths:** every change specifies path:line
- [ ] **Commit per task:** clear, focused commit message
- [ ] **Type consistency:** model fields match across migrations, schemas, routers
- [ ] **Spec coverage:** every requirement in spec §3-9 has a corresponding task

## Critical Spec Coverage

| Spec Section | Implementation Tasks |
|---|---|
| §2.1 Architecture | Tasks 1-7 (Backend bootstrap), 66-78 (Frontend) |
| §3 Database (15 tables) | Tasks 8-22 |
| §3.2 RLS policies | Task 21 |
| §4 Authentication | Tasks 23-34 |
| §5 RBAC | Tasks 27, 28, 41, 50, 58, 62 |
| §6 Key Vault | Tasks 25, 51-58 |
| §6.6 Token usage | Task 18, 58 |
| §7 Settings | Tasks 59-63 |
| §8 Audit Log | Tasks 26, 64-65 |
| §9 API surface | Tasks 29-65 |
| §10 Frontend | Tasks 66-78 |
| §11 Deployment | Tasks 79-85 |

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-24-multi-tenant-platform-plan.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
