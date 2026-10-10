"""Daily pipeline for one or all workspaces: aggregate real traffic -> forecast -> anomaly detection.

uv run python -m app.jobs.predict            # all workspaces
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Workspace
from app.services.anomaly import detect_and_store
from app.services.forecast import run_forecast
from app.services.history import aggregate_real_usage
from app.services.retention import purge_expired


def run_for_workspace(session: Session, ws: Workspace, today: date | None = None) -> dict:
    today = today or datetime.now(ZoneInfo(ws.timezone)).date()
    real_rows = aggregate_real_usage(session, ws, through=today - timedelta(days=1))
    run = run_forecast(session, ws, today=today)
    anomalies = detect_and_store(session, ws, today=today)
    retained = purge_expired(session, ws)
    return {
        "retention": retained,
        "workspace": ws.slug,
        "real_daily_rows": real_rows,
        "forecast_run_id": str(run.id),
        "forecast_status": run.status,
        "model": run.model_name,
        "anomalies": anomalies,
    }


def run_all(session: Session) -> list[dict]:
    return [run_for_workspace(session, ws) for ws in session.scalars(select(Workspace))]


if __name__ == "__main__":
    with Session(get_engine()) as s:
        for result in run_all(s):
            print(result)
