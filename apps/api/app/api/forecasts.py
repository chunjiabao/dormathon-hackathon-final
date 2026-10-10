import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import CurrentUser, DbSession, require_member
from app.errors import ApiError
from app.models import ForecastRun, Workspace
from app.services.drivers import forecast_drivers
from app.services.forecast import budget_crossing_date, budget_risk, daily_series, latest_run, run_forecast

router = APIRouter(tags=["forecasts"])


class ForecastRunRequest(BaseModel):
    workspace_id: uuid.UUID | None = None
    run_key: str | None = Field(default=None, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")


def evidence_type(run: ForecastRun) -> str:
    mix = run.data_mix_json or {}
    if "synthetic" in mix and "real" in mix:
        return "synthetic_and_real"
    return "synthetic" if "synthetic" in mix else "real" if "real" in mix else "none"


def serialize_run(session, run: ForecastRun, include_series: bool = True) -> dict:
    out = {
        "id": str(run.id),
        "status": run.status,
        "generated_at": run.generated_at.isoformat(),
        "training_cutoff": str(run.training_cutoff),
        "horizon_end": str(run.horizon_end),
        "model_name": run.model_name,
        "model_version": run.model_version,
        "budget_myr": float(run.budget_myr),
        "observed_to_date_myr": float(run.observed_to_date_myr),
        "predicted_remaining_myr": float(run.predicted_remaining_myr),
        "forecast_total_myr": float(run.forecast_total_myr),
        "lower_myr": float(run.lower_myr),
        "upper_myr": float(run.upper_myr),
        "budget_risk": budget_risk(run),
        "evidence_type": evidence_type(run),
        "data_mix": run.data_mix_json,
        "metrics": run.metrics_json,
        "assumptions": run.assumptions_json,
    }
    if include_series and run.status == "ok":
        series = daily_series(session, run)
        out["series"] = series
        out["budget_crossing_date"] = budget_crossing_date(series, float(run.budget_myr))
        today = run.assumptions_json.get("today")
        nxt = [r for r in series if r["kind"] == "forecast" and r["day"] >= today][:7]
        out["next_7_days_myr"] = round(sum(r["cost_myr"] for r in nxt), 4) if len(nxt) == 7 else None
    return out


@router.post("/forecasts/run")
def trigger_forecast(body: ForecastRunRequest, principal: CurrentUser, session: DbSession) -> dict:
    m = require_member(session, principal, body.workspace_id, role="owner")
    try:
        run = run_forecast(session, session.get(Workspace, m.workspace_id), run_key=body.run_key)
    except ValueError as exc:
        raise ApiError(409, "conflict", "run_key already used.") from exc
    return serialize_run(session, run)


@router.get("/forecasts/latest")
def get_latest(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    m = require_member(session, principal, workspace_id)
    run = latest_run(session, m.workspace_id)
    if run is None:
        return {"status": "no_forecast", "message": "No forecast has been run for this workspace yet."}
    return serialize_run(session, run)


@router.get("/forecasts/{forecast_id}/drivers")
def get_drivers(forecast_id: uuid.UUID, principal: CurrentUser, session: DbSession) -> dict:
    run = session.get(ForecastRun, forecast_id)
    if run is None:
        raise ApiError(404, "not_found", "Forecast not found.")
    require_member(session, principal, run.workspace_id)  # 404 for non-members
    return {"forecast_id": str(run.id), **forecast_drivers(session, run)}


@router.get("/forecasts")
def list_forecasts(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    m = require_member(session, principal, workspace_id)
    runs = session.scalars(
        select(ForecastRun)
        .where(ForecastRun.workspace_id == m.workspace_id)
        .order_by(ForecastRun.generated_at.desc())
        .limit(20)
    )
    return {"items": [serialize_run(session, r, include_series=False) for r in runs], "next_cursor": None}
