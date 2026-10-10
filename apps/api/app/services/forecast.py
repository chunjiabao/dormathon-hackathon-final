"""Workspace forecast runs: month-to-date actuals + forecast of the remaining days.

Month-to-date actuals (complete days up to the training cutoff) are counted exactly once; every
later day of the month (including today and any data gap) is forecast. The model is selected per
run on a calibration window (the last 28 complete days, rolling origins retrained per origin):
the HistGradientBoosting candidate ships only if it beats seasonal naive on workspace WAPE.
Interval bounds are relative residual quantiles from that calibration window.
"""

import calendar
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ml.backtest import (
    ALL_MODELS,
    INTERVAL_LEVEL,
    calibrate,
    quantile_for,
    rolling_backtest,
    score,
    select_model,
)
from app.ml.features import SEG, segment_panel
from app.ml.train_forecast import fit_predict
from app.models import ForecastPoint, ForecastRun, Workspace
from app.services.history import app_maps, load_daily

MIN_HISTORY_DAYS = 56
CALIBRATION_DAYS = 28
CALIBRATION_STEP = 4
MODEL_VERSION = "forecast-v1"


def _d(x: float, places: str = "0.0001") -> Decimal:
    return Decimal(str(round(float(x), 6))).quantize(Decimal(places))


def month_bounds(day: date) -> tuple[date, date]:
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _data_mix(hist: pd.DataFrame) -> dict:
    total = float(hist.cost_myr.sum()) or 1.0
    mix = {}
    for origin, g in hist.groupby("data_origin"):
        mix[origin] = {
            "days": int(g.day.nunique()),
            "rows": len(g),
            "cost_myr": round(float(g.cost_myr.sum()), 4),
            "cost_share": round(float(g.cost_myr.sum()) / total, 4),
            "first_day": str(min(g.day)),
            "last_day": str(max(g.day)),
        }
    return mix


def run_forecast(session: Session, ws: Workspace, today: date | None = None, run_key: str | None = None) -> ForecastRun:
    if run_key:
        existing = session.scalar(select(ForecastRun).where(ForecastRun.run_key == run_key))
        if existing is not None:
            if existing.workspace_id != ws.id:
                raise ValueError("run_key belongs to another workspace")
            return existing
    tz = ZoneInfo(ws.timezone)
    today = today or datetime.now(tz).date()
    month_start, month_end = month_bounds(today)
    horizon_end = max(month_end, today + timedelta(days=6))  # + next-7-day estimate
    budget = Decimal(ws.monthly_budget_myr)
    hist = load_daily(session, ws.id, before=today)  # complete days only

    base = dict(workspace_id=ws.id, run_key=run_key, horizon_end=horizon_end, model_version=MODEL_VERSION,
                budget_myr=budget)  # fmt: skip
    n_days = hist.day.nunique() if len(hist) else 0
    if n_days < MIN_HISTORY_DAYS:
        run = ForecastRun(
            **base, training_cutoff=(max(hist.day) if len(hist) else today - timedelta(days=1)),
            model_name="none", data_mix_json=_data_mix(hist) if len(hist) else {},
            metrics_json={}, assumptions_json={"reason": f"Need >= {MIN_HISTORY_DAYS} days of history, have {n_days}."},
            forecast_total_myr=0, observed_to_date_myr=0, predicted_remaining_myr=0, lower_myr=0, upper_myr=0,
            status="insufficient_data",
        )  # fmt: skip
        session.add(run)
        session.commit()
        return run

    panel = segment_panel(hist)
    cutoff = panel.day.max()
    horizon_days = pd.date_range(cutoff + pd.Timedelta(days=1), pd.Timestamp(horizon_end), freq="D")

    # ---- model selection + calibration on the most recent complete days ----
    cal_start = cutoff - pd.Timedelta(days=CALIBRATION_DAYS - 1)
    origins = list(pd.date_range(cal_start, cutoff, freq=f"{CALIBRATION_STEP}D"))
    bts = {m: rolling_backtest(panel, m, "cost_myr", origins, horizon=CALIBRATION_DAYS, end=cutoff) for m in ALL_MODELS}
    scores = {m: score(bt) for m, bt in bts.items()}
    chosen, reason = select_model(scores)
    cal = calibrate(bts[chosen])

    # ---- final forecast from all history ----
    cost = fit_predict(chosen, panel, "cost_myr", horizon_days)
    reqs = fit_predict(chosen, panel, "requests", horizon_days).rename(columns={"yhat": "req_hat"})
    recent = (
        panel[panel.day > cutoff - pd.Timedelta(days=28)]
        .groupby(SEG)[["requests", "input_tokens", "output_tokens"]]
        .sum()
    )
    per_req = recent[["input_tokens", "output_tokens"]].div(recent.requests.clip(lower=1), axis=0).reset_index()
    pts = cost.merge(reqs, on=["day", *SEG]).merge(per_req, on=SEG, how="left").fillna(0.0)
    pts["h"] = (pts.day - cutoff).dt.days
    q_seg = np.array([quantile_for(cal["segment_daily_rel"], int(h))[0] for h in pts.h])
    pts["lower"] = np.clip(pts.yhat * (1 - q_seg), 0, None)
    pts["upper"] = pts.yhat * (1 + q_seg)

    # ---- month totals: actuals once + remaining forecast ----
    ms, me = pd.Timestamp(month_start), pd.Timestamp(month_end)
    observed = float(panel[(panel.day >= ms) & (panel.day <= cutoff)].cost_myr.sum())
    in_month = pts[(pts.day >= ms) & (pts.day <= me)]
    remaining = float(in_month.yhat.sum())
    n_rem = int(in_month.day.nunique())
    q_cum, extrapolated = quantile_for(cal["cumulative_total_rel"], n_rem) if n_rem else (0.0, False)
    total = observed + remaining

    _, name_to_id = app_maps(session, ws.id)
    settings = get_settings()
    data_hash = hashlib.sha256(
        json.dumps([str(cutoff.date()), round(float(panel.cost_myr.sum()), 6), len(panel)]).encode()
    ).hexdigest()[:12]
    run = ForecastRun(
        **base,
        training_cutoff=cutoff.date(),
        model_name=chosen,
        data_mix_json=_data_mix(hist),
        metrics_json={
            "calibration_window": [str(cal_start.date()), str(cutoff.date())],
            "calibration_origins": len(origins),
            "selection_reason": reason,
            "calibration_scores": {m: s["workspace_daily"] for m, s in scores.items()},
            "interval_quantiles": cal,
        },
        assumptions_json={
            "today": str(today),
            "timezone": ws.timezone,
            "observed_through": str(cutoff.date()),
            "forecast_from": str(horizon_days[0].date()) if len(horizon_days) else None,
            "data_gap_days": max(0, (pd.Timestamp(today) - cutoff).days - 1),
            "interval": f"{INTERVAL_LEVEL:.0%} empirical interval from calibration residuals; may under-cover "
            "under distribution shift",
            "month_interval_extrapolated": extrapolated,
            "tokens_method": "predicted requests x trailing 28-day tokens per request",
            "fx_myr_per_usd_demo": settings.myr_per_usd_demo,
            "pricing_catalog_version": settings.pricing_catalog_version,
            "model_version_hash": data_hash,
        },  # fmt: skip
        forecast_total_myr=_d(total),
        observed_to_date_myr=_d(observed),
        predicted_remaining_myr=_d(remaining),
        lower_myr=_d(observed + remaining * (1 - q_cum)),
        upper_myr=_d(observed + remaining * (1 + q_cum)),
        status="ok",
    )
    session.add(run)
    session.flush()
    for r in pts.itertuples():
        session.add(
            ForecastPoint(
                forecast_run_id=run.id, day=r.day.date(), application_id=name_to_id[r.app_id],
                request_category=r.request_category, predicted_requests=_d(r.req_hat),
                predicted_input_tokens=_d(r.req_hat * r.input_tokens, "0.01"),
                predicted_output_tokens=_d(r.req_hat * r.output_tokens, "0.01"),
                predicted_cost_myr=_d(r.yhat, "0.000001"), lower_cost_myr=_d(r.lower, "0.000001"),
                upper_cost_myr=_d(r.upper, "0.000001"),
            )
        )  # fmt: skip
    session.commit()
    return run


def budget_risk(run: ForecastRun) -> str:
    """Deterministic thresholds; no fabricated probabilities."""
    if run.status != "ok":
        return "unknown"
    if run.lower_myr > run.budget_myr:
        return "high_confidence_overrun"
    if run.forecast_total_myr > run.budget_myr:
        return "projected_overrun"
    if run.upper_myr > run.budget_myr:
        return "possible_overrun"
    return "within_budget"


def latest_run(session: Session, workspace_id: uuid.UUID) -> ForecastRun | None:
    return session.scalar(
        select(ForecastRun).where(ForecastRun.workspace_id == workspace_id).order_by(ForecastRun.generated_at.desc())
    )


def daily_series(session: Session, run: ForecastRun) -> list[dict]:
    """Per-day workspace totals for the run's month: actual (observed) or forecast with bounds."""
    month_start, month_end = month_bounds(date.fromisoformat(run.assumptions_json.get("today", str(run.horizon_end))))
    hist = load_daily(session, run.workspace_id)
    out = []
    if len(hist):
        h = hist[(hist.day >= month_start) & (hist.day <= run.training_cutoff)]
        for day, g in h.groupby("day"):
            out.append({"day": str(day), "kind": "actual", "cost_myr": round(float(g.cost_myr.sum()), 4),
                        "origins": sorted(set(g.data_origin))})  # fmt: skip
    pts = session.execute(
        select(ForecastPoint.day, ForecastPoint.predicted_cost_myr, ForecastPoint.lower_cost_myr,
               ForecastPoint.upper_cost_myr).where(ForecastPoint.forecast_run_id == run.id)
    ).all()  # fmt: skip
    if pts:
        f = pd.DataFrame(pts, columns=["day", "yhat", "lo", "hi"]).astype({"yhat": float, "lo": float, "hi": float})
        for day, g in f.groupby("day"):
            out.append({"day": str(day), "kind": "forecast", "cost_myr": round(g.yhat.sum(), 4),
                        "lower_myr": round(g.lo.sum(), 4), "upper_myr": round(g.hi.sum(), 4),
                        "in_month": month_start <= day <= month_end})  # fmt: skip
    return sorted(out, key=lambda r: r["day"])


def budget_crossing_date(series: list[dict], budget: float) -> str | None:
    """First day the cumulative (actual + central forecast) curve exceeds budget within the month."""
    cum = 0.0
    for r in series:
        if r["kind"] == "forecast" and not r.get("in_month", True):
            continue
        cum += r["cost_myr"]
        if cum > budget:
            return r["day"]
    return None
