from fastapi import Depends, FastAPI

from app.config import get_settings
from app.deps import get_current_user

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


@app.get("/api/v1/test-me")
async def test_me(current_user: dict = Depends(get_current_user)) -> dict:
    """Debug endpoint that returns the current user's JWT claims."""
    return {"email": current_user.get("email"), "sub": current_user.get("sub")}
