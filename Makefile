.PHONY: dev-infra dev-infra-down backend frontend test lint migrate migrate-new clean

dev-infra:
	cd backend && docker compose -f docker-compose.dev.yml up -d

dev-infra-down:
	cd backend && docker compose -f docker-compose.dev.yml down

dev-infra-logs:
	cd backend && docker compose -f docker-compose.dev.yml logs -f

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && pnpm dev

test:
	cd backend && uv run pytest -v

test-cov:
	cd backend && uv run pytest -v --cov=app --cov-report=term-missing

lint:
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run mypy app

lint-fix:
	cd backend && uv run ruff check --fix .
	cd backend && uv run ruff format .

migrate:
	cd backend && uv run alembic upgrade head

migrate-new:
	cd backend && uv run alembic revision --autogenerate -m "$(name)"

migrate-down:
	cd backend && uv run alembic downgrade -1

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
