from fastapi import APIRouter, Response

from app.config import get_settings
from app.db import ping_database
from app.services import embeddings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(response: Response) -> dict:
    """Readiness and dependency summary. Never includes secrets."""
    settings = get_settings()
    db = ping_database()
    if db != "ok":
        response.status_code = 503
    return {
        "status": "ok" if db == "ok" else "degraded",
        "environment": settings.app_env,
        "dependencies": {
            "database": db,
            "anthropic": {"mode": settings.provider_mode, "model": settings.anthropic_model},
            "embeddings": embeddings.status(),
        },
        "demo_mode": settings.demo_mode,
        "pricing_catalog_version": settings.pricing_catalog_version,
    }
