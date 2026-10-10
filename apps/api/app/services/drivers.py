"""Forecast-linked cost drivers: segment shares of the predicted remaining spend.

Contribution = share of predicted remaining cost, and increment vs the segment's recent run rate
(mean of the last 14 complete days x remaining days). This is attribution of the forecast, not a
causal claim. Segment totals reconcile to the run's predicted remaining total.
"""

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ForecastPoint, ForecastRun
from app.services.forecast import month_bounds
from app.services.history import app_maps, load_daily

CATEGORY_LABELS = {
    "static_faq": "Static FAQs",
    "order_enquiry": "Order enquiries",
    "complex_support": "Complex support",
    "other": "Other requests",
}
RUN_RATE_DAYS = 14
RECONCILE_TOLERANCE_MYR = 0.01


def forecast_drivers(session: Session, run: ForecastRun) -> dict:
    if run.status != "ok":
        return {"status": run.status, "segments": [], "categories": [], "statements": []}
    today = date.fromisoformat(run.assumptions_json["today"])
    month_start, month_end = month_bounds(today)
    id_to_name, _ = app_maps(session, run.workspace_id)
    pts = session.execute(
        select(ForecastPoint.day, ForecastPoint.application_id, ForecastPoint.request_category,
               ForecastPoint.predicted_cost_myr, ForecastPoint.predicted_requests)
        .where(ForecastPoint.forecast_run_id == run.id, ForecastPoint.day >= month_start,
               ForecastPoint.day <= month_end)
    ).all()  # fmt: skip
    f = pd.DataFrame(pts, columns=["day", "application_id", "request_category", "cost", "requests"])
    f = f.astype({"cost": float, "requests": float})
    f["app"] = f.application_id.map(id_to_name)
    n_days = f.day.nunique()

    hist = load_daily(session, run.workspace_id, before=run.training_cutoff + timedelta(days=1))
    recent = hist[hist.day > run.training_cutoff - timedelta(days=RUN_RATE_DAYS)]
    run_rate = recent.groupby(["app_id", "request_category"]).cost_myr.sum() / RUN_RATE_DAYS

    total = float(f.cost.sum())
    seg = f.groupby(["app", "request_category"]).agg(cost=("cost", "sum"), requests=("requests", "sum"))
    segments = []
    for (app, cat), r in seg.iterrows():
        ref = float(run_rate.get((app, cat), 0.0)) * n_days
        segments.append({
            "application": app, "request_category": cat, "label": CATEGORY_LABELS.get(cat, cat),
            "predicted_remaining_myr": round(r.cost, 4), "predicted_requests": round(r.requests, 1),
            "share": round(r.cost / total, 4) if total else None,
            "recent_run_rate_reference_myr": round(ref, 4), "increment_vs_run_rate_myr": round(r.cost - ref, 4),
        })  # fmt: skip
    cats = []
    for cat, g in pd.DataFrame(segments).groupby("request_category") if segments else []:
        cost, ref = g.predicted_remaining_myr.sum(), g.recent_run_rate_reference_myr.sum()
        cats.append({
            "request_category": cat, "label": CATEGORY_LABELS.get(cat, cat),
            "predicted_remaining_myr": round(cost, 4), "share": round(cost / total, 4) if total else None,
            "recent_run_rate_reference_myr": round(ref, 4), "increment_vs_run_rate_myr": round(cost - ref, 4),
        })  # fmt: skip
    cats.sort(key=lambda c: -c["predicted_remaining_myr"])
    segments.sort(key=lambda s: -s["predicted_remaining_myr"])

    diff = abs(total - float(run.predicted_remaining_myr))
    statements = []
    for c in cats[:3]:
        delta = c["increment_vs_run_rate_myr"]
        direction = "above" if delta >= 0 else "below"
        statements.append(
            f"{c['label']} account for RM{c['predicted_remaining_myr']:.2f} ({c['share']:.0%}) of projected "
            f"remaining spending, RM{abs(delta):.2f} {direction} their recent run rate."
        )
    return {
        "status": "ok",
        "period": {"from": str(min(f.day)) if len(f) else None, "to": str(month_end), "days": n_days},
        "predicted_remaining_myr": round(total, 4),
        "reconciles_with_forecast": diff <= RECONCILE_TOLERANCE_MYR,
        "reconciliation_difference_myr": round(diff, 6),
        "categories": cats,
        "segments": segments,
        "statements": statements,
        "method": "Share of forecast remaining cost per segment vs recent 14-day run rate; attribution, not causation.",
    }
