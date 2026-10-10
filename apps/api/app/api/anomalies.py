import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from sqlalchemy import select

from app.auth import CurrentUser, DbSession, require_member
from app.errors import ApiError
from app.models import AnomalyEvent, PolicyAudit
from app.services.history import app_maps
from app.services.synthetic_loader import dataset_record

router = APIRouter(tags=["anomalies"])


def _ground_truth(session, workspace_id, app_name: str, day, end_day) -> dict | None:
    """For synthetic data only: the known injected mechanism overlapping this alert (if any)."""
    rec = dataset_record(session, workspace_id)
    if rec is None:
        return None
    for t in rec.metrics_json.get("anomaly_truth", []):
        if t["app_id"] == app_name and t["kind"] != "A8":
            if t["start_date"] <= str(end_day or day) and t["end_date"] >= str(day):
                return {"event_id": t["event_id"], "kind": t["kind"], "mechanism": t["mechanism"],
                        "event_class": t["event_class"], "alert_expected": t["alert_expected"]}  # fmt: skip
    return {
        "event_id": None,
        "mechanism": "No injected event overlaps this alert (false alarm on synthetic data).",
    }


@router.get("/anomalies")
def list_anomalies(
    principal: CurrentUser,
    session: DbSession,
    workspace_id: uuid.UUID | None = None,
    severity: Literal["low", "medium", "high"] | None = None,
) -> dict:
    m = require_member(session, principal, workspace_id)
    stmt = select(AnomalyEvent).where(AnomalyEvent.workspace_id == m.workspace_id)
    if severity:
        stmt = stmt.where(AnomalyEvent.severity == severity)
    id_to_name, _ = app_maps(session, m.workspace_id)
    items = []
    for e in session.scalars(stmt.order_by(AnomalyEvent.day.desc())):
        app_name = id_to_name.get(e.application_id)
        items.append({
            "id": str(e.id), "application": app_name, "day": str(e.day),
            "end_day": str(e.end_day) if e.end_day else None, "metric": e.metric,
            "observed_value": float(e.observed_value), "expected_value": float(e.expected_value),
            "estimated_impact_myr": float(e.estimated_impact_myr) if e.estimated_impact_myr is not None else None,
            "severity": e.severity, "anomaly_score": float(e.anomaly_score), "reason_code": e.reason_code,
            "explanation": e.explanation, "is_synthetic": e.is_synthetic,
            "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
            "synthetic_ground_truth": (
                _ground_truth(session, m.workspace_id, app_name, e.day, e.end_day) if e.is_synthetic else None
            ),
            "limitations": "Diagnostic correlation from usage metrics, not a proven cause. Score is a robust "
                           "z-score, not a probability.",
        })  # fmt: skip
    return {"items": items, "next_cursor": None}


@router.post("/anomalies/{anomaly_id}/acknowledge")
def acknowledge(anomaly_id: uuid.UUID, principal: CurrentUser, session: DbSession) -> dict:
    e = session.get(AnomalyEvent, anomaly_id)
    if e is None:
        raise ApiError(404, "not_found", "Anomaly not found.")
    require_member(session, principal, e.workspace_id, role="owner")
    if e.acknowledged_at is None:
        e.acknowledged_at = datetime.now(UTC)
        session.add(
            PolicyAudit(
                workspace_id=e.workspace_id, application_id=e.application_id, actor_user_id=principal.user_id,
                action="anomaly_acknowledged", old_value=None, new_value={"anomaly_id": str(e.id)},
            )
        )  # fmt: skip
        session.commit()
    return {"id": str(e.id), "acknowledged_at": e.acknowledged_at.isoformat()}
