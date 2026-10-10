"""ORM models for all TokenGuard tables (MASTER_BUILD_PACK §5).

Every tenant table carries workspace_id; services must always scope queries by the
authenticated workspace. Raw user messages are never stored.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

EMBEDDING_DIM = 384


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _ws_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )


def _app_fk(nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=nullable
    )


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    monthly_budget_myr: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    currency: Mapped[str] = mapped_column(Text, server_default="MYR", nullable=False)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Kuala_Lumpur", nullable=False)
    knowledge_version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("monthly_budget_myr >= 0", name="ck_workspaces_budget_nonneg"),)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    auth_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("workspace_id", "auth_user_id"),
        CheckConstraint("role IN ('owner','viewer')", name="ck_workspace_members_role"),
    )


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    app_key_hash: Mapped[str | None] = mapped_column(Text, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)


class ApiRequest(Base):
    __tablename__ = "api_requests"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    application_id: Mapped[uuid.UUID] = _app_fk()
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    request_category: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    estimated_cost_myr: Mapped[Decimal] = mapped_column(Numeric(14, 8), server_default="0", nullable=False)
    cache_status: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(Text, unique=True)
    data_origin: Mapped[str] = mapped_column(Text, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    # HMAC of the chat session / user / app key: lets retries be told apart from popular repeats.
    client_fingerprint: Mapped[str | None] = mapped_column(Text)
    pricing_version: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    # Safe-cache diagnostics (no raw text): gate decision, matched FAQ intent and similarity score.
    # cache_decision is recorded even while the cache policy is disabled ("shadow" evaluation).
    cache_decision: Mapped[str | None] = mapped_column(Text)
    faq_intent_key: Mapped[str | None] = mapped_column(Text)
    similarity_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    __table_args__ = (
        CheckConstraint(
            "cache_status IN ('miss','exact_hit','semantic_hit','bypass','error')",
            name="ck_api_requests_cache",
        ),
        CheckConstraint("data_origin IN ('real','synthetic')", name="ck_api_requests_origin"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cache_read_tokens >= 0 AND cache_write_tokens >= 0",
            name="ck_api_requests_tokens_nonneg",
        ),
        CheckConstraint("estimated_cost_myr >= 0", name="ck_api_requests_cost_nonneg"),
        Index("ix_api_requests_ws_time", "workspace_id", "occurred_at"),
    )


class FaqEntry(Base):
    __tablename__ = "faq_entries"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    application_id: Mapped[uuid.UUID] = _app_fk()
    intent_key: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    approved_answer: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, server_default="[]", nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_version: Mapped[int] = mapped_column(Integer, nullable=False)
    cacheable: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    __table_args__ = (UniqueConstraint("application_id", "intent_key", "locale", "knowledge_version"),)


class ResponseCache(Base):
    __tablename__ = "response_cache"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    application_id: Mapped[uuid.UUID] = _app_fk()
    faq_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faq_entries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    normalized_query_hash: Mapped[str] = mapped_column(Text, nullable=False)
    query_embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _now()
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hit_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    __table_args__ = (UniqueConstraint("application_id", "normalized_query_hash", "locale", "knowledge_version"),)


class DailyUsage(Base):
    __tablename__ = "daily_usage"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    application_id: Mapped[uuid.UUID] = _app_fk()
    day: Mapped[date] = mapped_column(Date, nullable=False)
    request_category: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    requests: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_myr: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    cache_hits: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    retry_requests: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    data_origin: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("workspace_id", "application_id", "day", "request_category", "model", "data_origin"),
        CheckConstraint("retry_requests >= 0", name="ck_daily_usage_retry_nonneg"),
        CheckConstraint(
            "requests >= 0 AND input_tokens >= 0 AND output_tokens >= 0 AND cost_myr >= 0 AND cache_hits >= 0",
            name="ck_daily_usage_nonneg",
        ),
        CheckConstraint("data_origin IN ('real','synthetic')", name="ck_daily_usage_origin"),
        Index("ix_daily_usage_ws_day", "workspace_id", "day"),
    )


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    run_key: Mapped[str | None] = mapped_column(Text, unique=True)
    generated_at: Mapped[datetime] = _now()
    horizon_end: Mapped[date] = mapped_column(Date, nullable=False)
    training_cutoff: Mapped[date] = mapped_column(Date, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    data_mix_json: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    assumptions_json: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    forecast_total_myr: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    observed_to_date_myr: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    predicted_remaining_myr: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    budget_myr: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    lower_myr: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    upper_myr: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)


class ForecastPoint(Base):
    __tablename__ = "forecast_points"
    id: Mapped[uuid.UUID] = _pk()
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    application_id: Mapped[uuid.UUID] = _app_fk()
    request_category: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_requests: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    predicted_input_tokens: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    predicted_output_tokens: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    predicted_cost_myr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    lower_cost_myr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    upper_cost_myr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "predicted_requests >= 0 AND predicted_cost_myr >= 0 AND lower_cost_myr >= 0",
            name="ck_forecast_points_nonneg",
        ),
    )


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    application_id: Mapped[uuid.UUID] = _app_fk()
    detected_at: Mapped[datetime] = _now()
    day: Mapped[date] = mapped_column(Date, nullable=False)
    end_day: Mapped[date | None] = mapped_column(Date)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    observed_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    expected_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    estimated_impact_myr: Mapped[Decimal | None] = mapped_column(Numeric)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    anomaly_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_anomaly_events_ws_day", "workspace_id", "day"),)


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = _now()
    scenario_type: Mapped[str] = mapped_column(Text, nullable=False)
    assumptions_json: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)
    baseline_cost_myr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    projected_cost_myr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    gross_savings_myr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    overhead_myr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    net_savings_myr: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False)
    uncertainty_json: Mapped[dict] = mapped_column(JSONB, server_default="{}", nullable=False)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scenario_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenario_runs.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID | None] = _app_fk(nullable=True)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="proposed", nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    created_at: Mapped[datetime] = _now()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed','approved','rejected','enabled','disabled')",
            name="ck_recommendations_status",
        ),
    )


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    application_id: Mapped[uuid.UUID] = _app_fk()
    policy_type: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    similarity_threshold: Mapped[Decimal] = mapped_column(Numeric, server_default="0.95", nullable=False)
    faq_only: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    ttl_hours: Mapped[int] = mapped_column(Integer, server_default="24", nullable=False)
    holdout_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _now()
    __table_args__ = (
        UniqueConstraint("application_id", "policy_type"),
        CheckConstraint("similarity_threshold BETWEEN 0.95 AND 0.99", name="ck_policies_threshold_range"),
        CheckConstraint("ttl_hours > 0", name="ck_policies_ttl_pos"),
    )


class PolicyAudit(Base):
    """Immutable: a DB trigger rejects UPDATE and DELETE (see migration 0001)."""

    __tablename__ = "policy_audit"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID] = _ws_fk()
    application_id: Mapped[uuid.UUID | None] = _app_fk(nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[uuid.UUID] = _pk()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    evaluated_at: Mapped[datetime] = _now()
    dataset_version: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    data_origin: Mapped[str] = mapped_column(Text, nullable=False)


class PricingCatalog(Base):
    __tablename__ = "pricing_catalog"
    id: Mapped[uuid.UUID] = _pk()
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    input_usd_per_million: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    output_usd_per_million: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    cache_read_usd_per_million: Mapped[Decimal | None] = mapped_column(Numeric)
    cache_write_usd_per_million: Mapped[Decimal | None] = mapped_column(Numeric)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (UniqueConstraint("provider", "model", "version"),)
