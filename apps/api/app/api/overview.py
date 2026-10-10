import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.forecasts import serialize_run
from app.auth import CurrentUser, DbSession, require_member
from app.models import AnomalyEvent, ApiRequest, Policy, Recommendation, Workspace
from app.services.drivers import forecast_drivers
from app.services.forecast import latest_run
from app.services.history import app_maps
from app.services.recommender import latest_forecast_id

router = APIRouter(tags=["overview"])


@router.get("/overview")
def overview(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    """Everything the Overview page needs, each value labelled with its provenance."""
    m = require_member(session, principal, workspace_id)
    ws = session.get(Workspace, m.workspace_id)
    names, _ = app_maps(session, ws.id)
    run = latest_run(session, ws.id)
    forecast = serialize_run(session, run) if run else None
    drivers = forecast_drivers(session, run) if run and run.status == "ok" else None

    latest_anomaly = session.scalar(
        select(AnomalyEvent).where(AnomalyEvent.workspace_id == ws.id).order_by(AnomalyEvent.day.desc())
    )
    open_alerts = session.scalar(
        select(func.count())
        .select_from(AnomalyEvent)
        .where(AnomalyEvent.workspace_id == ws.id, AnomalyEvent.acknowledged_at.is_(None))
    )
    rec = session.scalar(
        select(Recommendation).where(Recommendation.workspace_id == ws.id).order_by(Recommendation.created_at.desc())
    )
    since = datetime.now(UTC) - timedelta(days=7)
    traffic = session.execute(
        select(ApiRequest.cache_status, func.count())
        .where(ApiRequest.workspace_id == ws.id, ApiRequest.occurred_at >= since, ApiRequest.data_origin == "real")
        .group_by(ApiRequest.cache_status)
    ).all()  # fmt: skip
    counts = dict(traffic)
    total = sum(counts.values())
    hits = counts.get("exact_hit", 0) + counts.get("semantic_hit", 0)
    policies = session.scalars(select(Policy).where(Policy.workspace_id == ws.id))
    return {
        "workspace": {
            "id": str(ws.id),
            "name": ws.name,
            "budget_myr": float(ws.monthly_budget_myr),
            "currency": ws.currency,
            "timezone": ws.timezone,
        },  # fmt: skip
        "forecast": forecast,
        "top_drivers": drivers["categories"][:4] if drivers else [],
        "driver_statements": drivers["statements"] if drivers else [],
        "latest_anomaly": None
        if latest_anomaly is None
        else {
            "id": str(latest_anomaly.id),
            "day": str(latest_anomaly.day),
            "application": names.get(latest_anomaly.application_id),
            "reason_code": latest_anomaly.reason_code,
            "severity": latest_anomaly.severity,
            "explanation": latest_anomaly.explanation,
            "is_synthetic": latest_anomaly.is_synthetic,
        },  # fmt: skip
        "open_alerts": open_alerts,
        "recommendation": None
        if rec is None
        else {
            "id": str(rec.id),
            "action_type": rec.action_type,
            "status": rec.status,
            "rationale": rec.rationale,
            "superseded": rec.forecast_run_id != latest_forecast_id(session, ws.id),
        },  # fmt: skip
        "live_traffic_7d": {
            "requests": total,
            "cache_hits": hits,
            "by_status": counts,
            "cache_hit_rate": hits / total if total else None,
            "data_origin": "real",
        },  # fmt: skip
        "policies": [
            {
                "id": str(p.id),
                "application": names.get(p.application_id),
                "enabled": p.enabled,
                "similarity_threshold": float(p.similarity_threshold),
            }
            for p in policies
        ],  # fmt: skip
    }
