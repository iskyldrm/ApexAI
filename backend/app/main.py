from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="ApexAI API",
    version="0.1.0",
    description="Multi-tenant AI agent platform",
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)


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
