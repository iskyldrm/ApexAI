from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.agent.api.routes import router as agent_router
from app.agent.observability import init_tracing
from app.cost.api import router as cost_router
from app.testing.api import router as test_runs_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.invitations import router as invitations_router
from app.api.v1.keys import router as keys_router
from app.api.v1.orgs import router as orgs_router
from app.api.v1.settings import router as settings_router
from app.config import get_settings
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS, metrics_response
from app.deps import get_current_user
from app.workflow.api.routes import dlq_router, processes_router, router as process_router
from app.workflow.api.task_routes import (
    activity_router,
    notifications_router,
    tasks_router,
)
import logging
import time

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Initialize OpenTelemetry tracing + FastAPI auto-instrumentation on startup."""
    try:
        init_tracing("apexai-api")
        # Auto-instrument FastAPI so HTTP requests get a parent span
        # (children like agent.run inherit trace context).
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("OpenTelemetry tracing initialized")
    except Exception:
        logger.exception("Failed to initialize tracing — continuing without spans")

    # A.9 — Failure recovery: mark any stuck agent_runs as interrupted on startup.
    # Runs that have been in 'running' state for over an hour with no
    # progress almost certainly crashed. Resumable via POST /agent/runs/{id}/resume.
    try:
        from app.agent.checkpoint import mark_stuck_runs_interrupted
        from app.db import async_session_maker

        async with async_session_maker() as session:
            n = await mark_stuck_runs_interrupted(session, threshold_seconds=3600)
            if n:
                logger.warning("Startup: marked %d stuck agent runs as interrupted", n)
    except Exception:
        logger.exception("Startup stuck-run cleanup failed (non-fatal)")

    yield


app = FastAPI(
    title="ApexAI API",
    version="0.1.0",
    description="Multi-tenant AI agent platform",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    lifespan=lifespan,
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record HTTP request count + latency for Prometheus."""
    if not settings.metrics_enabled:
        return await call_next(request)
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    # route path is filled in by FastAPI on response.scope
    path = request.scope.get("route").path if request.scope.get("route") else request.url.path
    HTTP_LATENCY.labels(method=request.method, path=path).observe(elapsed)
    HTTP_REQUESTS.labels(
        method=request.method, path=path, status=response.status_code
    ).inc()
    return response


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    body, content_type = metrics_response()
    return Response(content=body, media_type=content_type)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(orgs_router, prefix="/api/v1")
app.include_router(invitations_router, prefix="/api/v1")
app.include_router(keys_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(process_router, prefix="/api/v1")  # DLQ router
app.include_router(processes_router, prefix="/api/v1")  # /processes CRUD
app.include_router(dlq_router, prefix="/api/v1")  # /process-dlq
app.include_router(tasks_router, prefix="/api/v1")  # /tasks
app.include_router(notifications_router, prefix="/api/v1")  # /notifications
app.include_router(activity_router, prefix="/api/v1")  # /activity-feed
app.include_router(cost_router)  # /api/v1/cost/* (tiers, usage, alerts)
app.include_router(test_runs_router)  # /api/v1/test-runs/* (Sub-System E)


@app.get("/health")
async def health_check() -> dict:
    """Liveness probe — process is alive."""
    return {"status": "healthy"}


@app.get("/ready")
async def readiness_check() -> dict:
    """Readiness probe — dependencies available.

    Extended in later phases to check DB, Redis, Vault.
    """
    return {"status": "ready"}


@app.get("/")
async def root() -> dict:
    return {
        "name": settings.app_env,
        "version": app.version,
        "docs": "/api/v1/docs",
    }


@app.get("/api/v1/test-me")
async def test_me(current_user: dict = Depends(get_current_user)) -> dict:
    """Debug endpoint that returns the current user's JWT claims."""
    return {"email": current_user.get("email"), "sub": current_user.get("sub")}
