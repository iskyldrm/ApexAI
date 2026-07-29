# ApexAI Helm Chart

Deploys the FastAPI backend and Next.js frontend to Kubernetes.

ApexAI's A/B/C sub-systems all run inside the backend FastAPI
process — agent runtime, workflow orchestrator, and task tracking
share the same image. So the chart only deploys **two** workloads.

## Layout

```
deploy/helm/
├── Chart.yaml
├── values.yaml
├── README.md
└── templates/
    ├── _helpers.tpl
    ├── backend-deployment.yaml   # FastAPI + /metrics
    ├── frontend-deployment.yaml  # Next.js
    ├── hpa.yaml                  # HorizontalPodAutoscaler
    ├── ingress.yaml              # nginx + cert-manager
    └── secrets.yaml              # jwt-secret, vault-token
```

## Install (dev)

```bash
# Bring up the dev infra first (Postgres + Redis + Vault on host)
make dev-infra

# Lint + dry-run
helm lint deploy/helm
helm template apexai deploy/helm/ > /tmp/rendered.yaml

# Install
helm install apexai deploy/helm/ \
  --set env.jwt_secret="$(openssl rand -base64 48)" \
  --set env.vault_token="$VAULT_TOKEN" \
  --set env.database_url="postgresql+psycopg://apexai:$PG_PASS@postgres:5432/apexai"
```

## Production override

```yaml
# values.prod.yaml
replicaCount: 5
ingress:
  api:
    host: api.apexai.com
  app:
    host: app.apexai.com
env:
  cookie_secure: "true"
  cors_origins: "https://app.apexai.com"
  metrics_enabled: "true"
autoscaling:
  maxReplicas: 30
```

```bash
helm upgrade --install apexai deploy/helm/ \
  -f deploy/helm/values.yaml \
  -f deploy/helm/values.prod.yaml
```

## CI/CD

- `.github/workflows/ci.yml` — on every push to main: backend tests +
  frontend build + helm lint + docker build & push to ghcr.io
- `.github/workflows/cd.yml` — manual deploy via workflow_dispatch,
  picks image tag, runs smoke test. Replace the placeholder SSH
  command with your actual rollout (ArgoCD, Flux, kubectl, Ansible).

## Prometheus scraping

Annotations on the backend pod:

- `prometheus.io/scrape: "true"`
- `prometheus.io/path: "/metrics"`
- `prometheus.io/port: "8000"`

The `/metrics` endpoint is opt-in via `metrics_enabled=true` in values.

Agent-specific metrics emitted by Sub-System A:

- `agent_runs_total{role, finish_reason, model}`
- `agent_run_duration_seconds{role}`
- `agent_tokens_total{role, model, direction}`
- `agent_run_steps{role}`

Workflow metrics emitted by Sub-System B:

- `processes_total{status}`
- `process_step_duration_seconds{role, status}`
- `process_dlq_open{role}`

## Single-host deploy (small installs)

If Kubernetes is overkill, use `docker-compose.prod.yml` at the repo
root:

```bash
cp .env.prod.example .env.prod
# edit secrets
docker compose -f docker-compose.prod.yml up -d
```

This brings up backend + frontend + the same Postgres/Redis/Vault
services as dev (single host, suitable for ≤ 100 RPS).
