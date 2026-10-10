"""Run anomaly detection over a workspace's daily usage and persist merged alert events.

Thresholds come from the latest offline evaluation (chosen on validation) when available,
otherwise documented defaults. The IsolationForest is refitted on the first 70% of the
workspace history. Acknowledged events are preserved across re-runs.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ml.train_anomaly import (
    WARMUP_DAYS,
    AnomalyDetector,
    DetectorConfig,
    app_day_features,
    explain,
    merge_alert_days,
    score_days,
    severity,
)
from app.models import AnomalyEvent, Workspace
from app.services.evaluation import latest_evaluation
from app.services.history import app_maps, load_daily

LOOKBACK_DAYS = 90
APP_LABELS = {
    "bakery_demo": "BakeryBot",
    "tuition_demo": "Tuition assistant",
    "retail_demo": "Retail assistant",
}


def detector_config(session: Session) -> tuple[DetectorConfig, str]:
    ev = latest_evaluation(session)
    if ev is not None:
        chosen = ev.metrics_json.get("anomaly", {}).get("chosen_config")
        if chosen:
            return DetectorConfig(**chosen), f"chosen on validation in evaluation run {ev.id}"
    return DetectorConfig(), "default thresholds (no evaluation run stored yet)"


def detect_and_store(session: Session, ws: Workspace, today: date | None = None) -> dict:
    today = today or datetime.now(ZoneInfo(ws.timezone)).date()
    hist = load_daily(session, ws.id, before=today)
    if hist.empty or hist.day.nunique() < WARMUP_DAYS + 14:
        return {"status": "insufficient_history", "events": 0}
    config, config_source = detector_config(session)
    scored = score_days(app_day_features(hist))
    days = sorted(scored.day.unique())
    train_end = days[int(len(days) * 0.7) - 1]
    detector = AnomalyDetector(config).fit(scored[scored.day <= train_end])
    pred = detector.predict(scored)
    since = pd.Timestamp(today - timedelta(days=LOOKBACK_DAYS))
    events = merge_alert_days(pred[pred.day >= since])

    origin_by_app_day = (
        hist.assign(day=pd.to_datetime(hist.day))
        .groupby(["app_id", "day"])
        .apply(
            lambda g: float(g[g.data_origin == "synthetic"].cost_myr.sum()) >= 0.5 * float(g.cost_myr.sum()),
            include_groups=False,
        )
    )
    _, name_to_id = app_maps(session, ws.id)
    acked = {
        (e.application_id, e.day, e.reason_code)
        for e in session.scalars(
            select(AnomalyEvent).where(AnomalyEvent.workspace_id == ws.id, AnomalyEvent.acknowledged_at.is_not(None))
        )
    }
    session.execute(
        delete(AnomalyEvent).where(AnomalyEvent.workspace_id == ws.id, AnomalyEvent.acknowledged_at.is_(None))
    )
    stored = 0
    for e in events.to_dict(orient="records"):
        app_id = name_to_id[e["app_id"]]
        key = (app_id, e["start"].date(), e["reason_code"])
        if key in acked:
            continue
        metric, text, observed, expected = explain(e, APP_LABELS.get(e["app_id"], e["app_id"]))
        session.add(
            AnomalyEvent(
                workspace_id=ws.id, application_id=app_id, day=e["start"].date(), end_day=e["end"].date(),
                metric=metric, observed_value=Decimal(str(round(observed, 6))),
                expected_value=Decimal(str(round(expected, 6))),
                estimated_impact_myr=Decimal(str(round(e["impact_myr"], 4))),
                severity=severity(e, config.impact_floor_myr),
                anomaly_score=Decimal(str(round(e["max_z"], 3))), reason_code=e["reason_code"],
                explanation=text, is_synthetic=bool(origin_by_app_day.get((e["app_id"], e["start"]), False)),
            )
        )  # fmt: skip
        stored += 1
    session.commit()
    return {"status": "ok", "events": stored, "config": config.__dict__, "config_source": config_source,
            "lookback_days": LOOKBACK_DAYS}  # fmt: skip
