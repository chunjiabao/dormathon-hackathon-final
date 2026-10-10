"""Runtime configuration loaded from environment variables (never hardcode secrets)."""

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qs, urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../../.env"), extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://tokenguard:tokenguard@localhost:5432/tokenguard"

    # Auth (Supabase JWT via JWKS in hosted mode; local HS256 dev secret otherwise)
    supabase_url: str | None = None
    supabase_jwks_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    dev_jwt_secret: str = Field(default="dev-only-insecure-secret-change-me", repr=False)

    # Anthropic (server-only). Empty key => mock provider mode.
    anthropic_api_key: str | None = Field(default=None, repr=False)
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_mode: Literal["auto", "mock", "live"] = "auto"

    allowed_origins: list[str] = ["http://localhost:3000"]
    myr_per_usd_demo: float = 4.70
    demo_mode: bool = True
    pricing_catalog_version: str = "demo-2025-10"
    scheduler_secret: str | None = Field(default=None, repr=False)
    monthly_budget_myr_default: float = 200.0

    # Signs short-lived, scoped BakeryBot chat tokens. Falls back to DEV_JWT_SECRET outside production.
    chat_token_secret: str | None = Field(default=None, repr=False)
    chat_token_ttl_minutes: int = 30
    # HMAC key for request fingerprints (so short messages cannot be recovered by hashing guesses).
    fingerprint_secret: str | None = Field(default=None, repr=False)

    # Per-minute rate limits (in-process; single instance only).
    rate_limit_ip_per_min: int = 30
    rate_limit_app_per_min: int = 120
    rate_limit_workspace_per_min: int = 300

    # Safe FAQ cache. Embeddings are local (no LLM, no external API); "disabled" => exact matching only.
    embedding_mode: Literal["local", "disabled"] = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_cache_dir: str | None = None
    semantic_margin: float = 0.03
    cache_overhead_per_lookup_myr: float = 0.00005  # assumption: local embedding + DB lookup
    cache_fixed_daily_myr: float = 0.20  # assumption: share of hosting/DB attributable to the cache

    request_retention_days: int = Field(default=30, ge=1, le=365)
    aggregate_retention_days: int = Field(default=180, ge=60, le=3650)

    chat_max_chars: int = 1000
    chat_max_output_tokens: int = 250
    provider_timeout_s: float = 25.0
    provider_max_retries: int = 2

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def provider_mode(self) -> Literal["mock", "live"]:
        if self.anthropic_mode == "mock":
            return "mock"
        if self.anthropic_mode == "live":
            return "live"
        return "live" if self.anthropic_api_key else "mock"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def dev_auth_enabled(self) -> bool:
        """Local HS256 dev tokens are accepted only outside production and without Supabase JWKS."""
        return not self.is_production and not self.supabase_jwks_url

    @property
    def effective_chat_token_secret(self) -> str:
        return self.chat_token_secret or self.dev_jwt_secret

    @property
    def effective_fingerprint_secret(self) -> str:
        return self.fingerprint_secret or self.dev_jwt_secret


def validate_settings(settings: Settings) -> Settings:
    if settings.is_production:
        if "*" in settings.allowed_origins:
            raise RuntimeError("ALLOWED_ORIGINS must not contain '*' in production.")
        if settings.demo_mode:
            raise RuntimeError("DEMO_MODE must be false in production.")
        if not settings.supabase_jwks_url:
            raise RuntimeError("SUPABASE_JWKS_URL is required in production (dev tokens are disabled).")
        if not settings.supabase_url or not settings.supabase_url.startswith("https://"):
            raise RuntimeError("SUPABASE_URL must be an HTTPS project URL in production (JWT issuer verification).")
        expected_jwks = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        if settings.supabase_jwks_url != expected_jwks:
            raise RuntimeError("SUPABASE_JWKS_URL must belong to the configured Supabase project.")
        if not settings.allowed_origins or any(not o.startswith("https://") for o in settings.allowed_origins):
            raise RuntimeError("ALLOWED_ORIGINS must contain explicit HTTPS frontend origins in production.")
        for name in ("chat_token_secret", "fingerprint_secret", "scheduler_secret"):
            value = getattr(settings, name)
            if not value or len(value) < 32 or value.lower().startswith("change-me"):
                raise RuntimeError(f"{name.upper()} must be a random string of at least 32 characters in production.")
        sslmode = parse_qs(urlparse(settings.database_url).query).get("sslmode", [None])[0]
        if sslmode not in {"require", "verify-ca", "verify-full"}:
            raise RuntimeError("DATABASE_URL must require TLS with sslmode=require (or stronger) in production.")
    return settings


@lru_cache
def get_settings() -> Settings:
    return validate_settings(Settings())
