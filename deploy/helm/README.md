# ApexAI Helm Chart

Deploys the FastAPI backend and Next.js frontend.

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
# Bring up the dev infra first
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
autoscaling:
  maxReplicas: 30
```

```bash
helm upgrade --install apexai deploy/helm/ \
  -f deploy/helm/values.yaml \
  -f deploy/helm/values.prod.yaml
```

## Prometheus scraping

Annotations on the backend pod:

- `prometheus.io/scrape: "true"`
- `prometheus.io/path: "/metrics"`
- `prometheus.io/port: "8000"`

The `/metrics` endpoint is opt-in via `metrics_enabled=true` in values.
