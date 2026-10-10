from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select

from app.ml import train_forecast
from app.ml.backtest import calibrate, quantile_for, rolling_backtest, select_model
from app.ml.features import FEATURES, SEG, category_codes, make_features, segment_panel
from app.ml.metrics import classification_report, smape, wape
from app.ml.train_forecast import GBMRecursive, SeasonalNaive, end_features
from app.models import DailyUsage, ForecastPoint, ForecastRun, Workspace
from app.services.drivers import forecast_drivers
from app.services.forecast import budget_crossing_date, budget_risk, month_bounds, run_forecast

from .conftest import TODAY


@pytest.fixture(scope="module")
def panel(synthetic):
    return segment_panel(synthetic["daily"])


def _long(panel):
    return panel[["day", *SEG, "cost_myr", "exp_share"]].rename(columns={"cost_myr": "y"})


def test_features_do_not_use_current_or_future_values(panel):
    long = _long(panel)
    codes = category_codes(panel)
    base = make_features(long, codes)
    t = panel.day.unique()[100]
    perturbed = long.copy()
    perturbed.loc[perturbed.day >= t, "y"] *= 1000  # change day t and everything after
    pert = make_features(perturbed, codes)
    cols = [c for c in FEATURES]
    a = base[base.day == t][cols].to_numpy(float)
    b = pert[pert.day == t][cols].to_numpy(float)
    np.testing.assert_array_equal(a, b)


def test_fast_recursive_features_match_pandas_features(panel):
    long = _long(panel)
    codes = category_codes(panel)
    feats = make_features(long, codes)
    t = panel.day.unique()[150]
    for (app, cat), g in long[long.day < t].groupby(SEG):
        row = feats[(feats.day == t) & (feats.app_id == app) & (feats.request_category == cat)][FEATURES]
        fast = end_features(list(g.y), list(g.exp_share), pd.Timestamp(t), codes["app"][app], codes["cat"][cat])
        np.testing.assert_allclose(row.to_numpy(float)[0], np.array(fast, float), rtol=1e-9, equal_nan=True)


def test_forecasts_nonnegative_and_deterministic(panel):
    hist = panel[panel.day < panel.day.unique()[150]]
    days = pd.date_range(hist.day.max() + pd.Timedelta(days=1), periods=20)
    a = GBMRecursive().fit(hist, "cost_myr").predict(hist, days)
    b = GBMRecursive().fit(hist, "cost_myr").predict(hist, days)
    assert (a.yhat >= 0).all()
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 20 * hist[SEG].drop_duplicates().shape[0]


def test_seasonal_naive_repeats_last_week(panel):
    hist = panel[panel.day < panel.day.unique()[100]]
    days = pd.date_range(hist.day.max() + pd.Timedelta(days=1), periods=14)
    pred = SeasonalNaive().fit(hist, "cost_myr").predict(hist, days)
    last_week = hist[hist.day > hist.day.max() - pd.Timedelta(days=7)]
    for d in days:
        exp = last_week[last_week.day.dt.dayofweek == d.dayofweek].set_index(SEG).cost_myr
        got = pred[pred.day == d].set_index(SEG).yhat
        pd.testing.assert_series_equal(got.sort_index(), exp.sort_index(), check_names=False)


def test_backtest_only_sees_history_before_origin(panel, monkeypatch):
    seen = []
    real = train_forecast.fit_predict

    def spy(name, history, target, horizon_days):
        seen.append((history.day.max(), pd.Timestamp(horizon_days[0])))
        return real(name, history, target, horizon_days)

    monkeypatch.setattr("app.ml.backtest.fit_predict", spy)
    origins = list(panel.day.unique()[130:140:3])
    rolling_backtest(panel, "rolling_mean_7", "cost_myr", [pd.Timestamp(o) for o in origins], horizon=7)
    assert seen and all(last < first for last, first in seen)


def test_calibration_quantiles_monotone_and_extrapolation_flagged(panel):
    origins = [pd.Timestamp(o) for o in panel.day.unique()[126:150:4]]
    bt = rolling_backtest(panel, "seasonal_naive_7", "cost_myr", origins, horizon=14)
    cal = calibrate(bt)
    q = cal["cumulative_total_rel"]
    assert all(q[h] <= q[h + 1] for h in range(1, max(q)))
    assert quantile_for(q, max(q) + 5) == (q[max(q)], True)


def test_model_selection_requires_beating_seasonal_naive():
    def s(w):
        return {"workspace_daily": {"wape": w}}

    assert select_model({"hist_gradient_boosting": s(0.2), "seasonal_naive_7": s(0.3)})[0] == "hist_gradient_boosting"
    assert select_model({"hist_gradient_boosting": s(0.35), "seasonal_naive_7": s(0.3)})[0] == "seasonal_naive_7"


def test_metrics_zero_handling():
    assert wape([0, 0], [1, 2]) is None  # undefined, not faked
    assert smape([0, 0], [0, 0]) == 0.0
    r = classification_report([False, False], [False, False])
    assert r["precision"] is None and r["recall"] is None and r["false_positive_rate"] == 0.0


# ------------------------------------------------------------------ persisted forecast (DB)


def test_month_to_date_counted_once_and_totals_reconcile(seeded, session):
    run = session.get(ForecastRun, seeded["run_id"])
    assert run.status == "ok"
    ms, me = month_bounds(TODAY)
    observed = session.scalar(
        select(func.sum(DailyUsage.cost_myr)).where(
            DailyUsage.workspace_id == run.workspace_id,
            DailyUsage.day >= ms,
            DailyUsage.day <= run.training_cutoff,
        )
    )
    assert float(run.observed_to_date_myr) == pytest.approx(float(observed), abs=1e-3)
    first_point = session.scalar(select(func.min(ForecastPoint.day)).where(ForecastPoint.forecast_run_id == run.id))
    assert first_point == run.training_cutoff + timedelta(days=1)  # no day both observed and forecast
    rem = session.scalar(
        select(func.sum(ForecastPoint.predicted_cost_myr)).where(
            ForecastPoint.forecast_run_id == run.id, ForecastPoint.day <= me
        )
    )
    assert float(run.predicted_remaining_myr) == pytest.approx(float(rem), abs=0.01)
    assert float(run.forecast_total_myr) == pytest.approx(
        float(run.observed_to_date_myr) + float(run.predicted_remaining_myr), abs=1e-3
    )
    assert run.lower_myr <= run.forecast_total_myr <= run.upper_myr
    assert run.lower_myr >= run.observed_to_date_myr  # lower bound never below money already spent
    assert run.data_mix_json["synthetic"]["cost_share"] == 1.0
    assert run.horizon_end >= TODAY + timedelta(days=6)


def test_points_nonnegative_with_bounds(seeded, session):
    bad = session.scalar(
        select(func.count())
        .select_from(ForecastPoint)
        .where(
            ForecastPoint.forecast_run_id == seeded["run_id"],
            (ForecastPoint.predicted_cost_myr < 0)
            | (ForecastPoint.lower_cost_myr > ForecastPoint.predicted_cost_myr)
            | (ForecastPoint.upper_cost_myr < ForecastPoint.predicted_cost_myr),
        )
    )
    assert bad == 0


def test_segment_drivers_reconcile_to_forecast(seeded, session):
    run = session.get(ForecastRun, seeded["run_id"])
    d = forecast_drivers(session, run)
    assert d["reconciles_with_forecast"]
    assert sum(s["predicted_remaining_myr"] for s in d["segments"]) == pytest.approx(
        float(run.predicted_remaining_myr), abs=0.01
    )
    assert sum(c["share"] for c in d["categories"]) == pytest.approx(1.0, abs=1e-3)
    assert d["statements"] and d["statements"][0].startswith(d["categories"][0]["label"])


def test_budget_risk_thresholds():
    def run(lo, mid, hi, budget=200):
        return ForecastRun(status="ok", lower_myr=lo, forecast_total_myr=mid, upper_myr=hi, budget_myr=budget)

    assert budget_risk(run(210, 250, 300)) == "high_confidence_overrun"
    assert budget_risk(run(150, 250, 300)) == "projected_overrun"
    assert budget_risk(run(150, 180, 220)) == "possible_overrun"
    assert budget_risk(run(150, 170, 190)) == "within_budget"


def test_budget_crossing_only_when_curve_crosses():
    series = [{"day": "d1", "kind": "actual", "cost_myr": 100}, {"day": "d2", "kind": "forecast", "cost_myr": 90},
              {"day": "d3", "kind": "forecast", "cost_myr": 20}]  # fmt: skip
    assert budget_crossing_date(series, 200) == "d3"
    assert budget_crossing_date(series, 500) is None


def test_insufficient_history_is_reported_not_faked(session):
    ws = session.query(Workspace).filter_by(slug="other-ws").one()
    run = run_forecast(session, ws, today=TODAY)
    assert run.status == "insufficient_data"
    assert float(run.forecast_total_myr) == 0 and run.model_name == "none"


def test_run_key_is_idempotent(seeded, session):
    ws = session.get(Workspace, seeded["workspace_id"])
    first = run_forecast(session, ws, today=TODAY, run_key="test-key-1")
    again = run_forecast(session, ws, today=TODAY, run_key="test-key-1")
    assert first.id == again.id
