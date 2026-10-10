import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import anomalies, chat, decisions, demo, evaluation, forecasts, health, overview, usage
from app.api import settings as settings_api
from app.config import get_settings
from app.errors import install_error_handlers
from app.services import embeddings
from app.services.anthropic_adapter import AnthropicProvider, get_provider

API_PREFIX = "/api/v1"
log = logging.getLogger("tokenguard")


@asynccontextmanager
async def lifespan(_: FastAPI):
    provider = get_provider()
    if isinstance(provider, AnthropicProvider):
        # Fail fast with an actionable message instead of silently switching providers.
        provider.validate_model()
        log.info("Anthropic live mode: model %s validated", provider.model)
    else:
        log.warning("Anthropic MOCK mode: no real provider calls will be made.")
    embeddings.warm_in_background()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="TokenGuard API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-App-Key"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    install_error_handlers(app)
    for router in (
        health.router, chat.router, settings_api.router, demo.router, forecasts.router, anomalies.router,
        usage.router, evaluation.router, decisions.router, overview.router,
    ):  # fmt: skip
        app.include_router(router, prefix=API_PREFIX)
    return app


app = create_app()
