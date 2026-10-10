import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Header

from app.auth import CurrentUser, DbSession, require_member
from app.config import get_settings
from app.errors import ApiError
from app.jobs.predict import run_all
from app.services.evaluation import latest_evaluation
from app.services.synthetic_loader import dataset_record

router = APIRouter(tags=["evaluation"])


@router.get("/evaluation/latest")
def evaluation_latest(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    """Metrics produced by code from measured runs; 'not_run' until an evaluation has actually run."""
    m = require_member(session, principal, workspace_id)
    ev = latest_evaluation(session)
    ds = dataset_record(session, m.workspace_id)
    return {
        "status": "ok" if ev else "not_run",
        "evaluation": None
        if ev is None
        else {
            "id": str(ev.id),
            "evaluated_at": ev.evaluated_at.isoformat(),
            "dataset_version": ev.dataset_version,
            "seed": ev.seed,
            "method": ev.method,
            "data_origin": ev.data_origin,
            "artifact_path": ev.artifact_path,
            "results": {k: v for k, v in ev.metrics_json.items() if k != "anomaly_truth"},
        },  # fmt: skip
        "workspace_dataset": None if ds is None else ds.metrics_json.get("manifest"),
    }


@router.post("/jobs/daily")
def scheduled_daily(session: DbSession, x_scheduler_secret: Annotated[str | None, Header()] = None) -> dict:
    """Secured entry point for an external scheduler (Render cron or similar)."""
    secret = get_settings().scheduler_secret
    if not secret or not x_scheduler_secret or not hmac.compare_digest(secret, x_scheduler_secret):
        raise ApiError(401, "unauthorized", "Invalid scheduler credentials.")
    return {"results": run_all(session)}
