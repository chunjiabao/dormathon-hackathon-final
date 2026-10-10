"""Offline evaluation on the labelled synthetic dataset. Every number is computed here, never typed in.

Protocol (chronological 70/15/15 split from the dataset manifest):
- Forecasting: models are compared on rolling-origin backtests over the validation window; the
  shipped model is chosen on validation only; test-window backtests (retrained per origin) report
  final metrics and interval coverage. Month-end overrun classification uses frozen models.
- Anomalies: the IsolationForest is fitted on the training window; thresholds are swept and chosen
  on validation; held-out test metrics are reported once with the chosen configuration.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from app.ml.backtest import (
    ALL_MODELS,
    calibrate,
    interval_coverage,
    quantile_for,
    rolling_backtest,
    score,
    select_model,
    total_by_day,
)
from app.ml.features import segment_panel
from app.ml.metrics import classification_report, regression_report
from app.ml.train_anomaly import (
    AnomalyDetector,
    DetectorConfig,
    app_day_features,
    config_dict,
    merge_alert_days,
    score_days,
)
from app.ml.train_forecast import MODEL_FACTORIES

BUDGETS_MYR = (200.0, 225.0, 250.0)
Z_GRID = (3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0)
IF_GRID = (0.97, 0.98, 0.99, 0.995, 1.0)


def _split_days(manifest: dict) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    return {k: (pd.Timestamp(v[0]), pd.Timestamp(v[1])) for k, v in manifest["splits"].items()}


# --------------------------------------------------------------------------- forecasting


def _event_mask(bt: pd.DataFrame, truth: pd.DataFrame | None) -> pd.Series:
    """True for segment-days whose application is inside an injected event window (A1-A7)."""
    mask = pd.Series(False, index=bt.index)
    if truth is None:
        return mask
    for ev in truth[truth.kind != "A8"].itertuples():
        mask |= (bt.app_id == ev.app_id) & bt.day.between(pd.Timestamp(ev.start_date), pd.Timestamp(ev.end_date))
    return mask


def evaluate_forecast(
    daily: pd.DataFrame,
    manifest: dict,
    truth: pd.DataFrame | None = None,
    test_step: int = 4,
    horizon: int = 14,
) -> dict:
    panel = segment_panel(daily)
    sp = _split_days(manifest)
    val_start, val_end = sp["validation"]
    test_start, test_end = sp["test"]

    val_origins = list(pd.date_range(val_start, val_end, freq="2D"))
    val_bt = {
        m: rolling_backtest(panel, m, "cost_myr", val_origins, horizon=(val_end - val_start).days + 1, end=val_end)
        for m in ALL_MODELS
    }
    val_scores = {m: score(bt[bt.h <= horizon]) for m, bt in val_bt.items()}
    chosen, reason = select_model(val_scores)
    cal = calibrate(val_bt[chosen])

    test_origins = [o for o in pd.date_range(test_start, test_end, freq=f"{test_step}D") if (test_end - o).days >= 6]
    test_bt = {m: rolling_backtest(panel, m, "cost_myr", test_origins, horizon=horizon) for m in ALL_MODELS}
    test_scores = {m: score(bt) for m, bt in test_bt.items()}
    for m, bt in test_bt.items():
        clean = bt[~_event_mask(bt, truth)]
        # Supplementary: segment-days outside injected-event windows (labels used for scoring only).
        test_scores[m]["segment_daily_excluding_event_days"] = regression_report(clean.y, clean.yhat)
    req_scores = {
        m: score(rolling_backtest(panel, m, "requests", test_origins, horizon=horizon))["workspace_daily"]
        for m in ALL_MODELS
    }

    plot = total_by_day(test_bt[chosen]).merge(
        total_by_day(test_bt["seasonal_naive_7"])[["origin", "day", "yhat"]].rename(columns={"yhat": "baseline"}),
        on=["origin", "day"],
    )
    return {
        "target": "daily cost (MYR) per application x category, aggregated to workspace",
        "data_origin": "synthetic",
        "models": ALL_MODELS,
        "selection": {"chosen": chosen, "reason": reason, "selected_on": "validation"},
        "validation": {
            "origins": [o.date().isoformat() for o in val_origins],
            "horizon_days": horizon,
            "scores": val_scores,
        },  # fmt: skip
        "test": {
            "origins": [o.date().isoformat() for o in test_origins],
            "horizon_days": horizon,
            "retrained_per_origin": True,
            "scores": test_scores,
            "requests_target_scores": req_scores,
            "interval_coverage": interval_coverage(test_bt[chosen], cal),
        },
        "calibration": cal,
        "overrun_classification": _overrun_eval(panel, chosen, cal, sp),
        "backtest_plot": [
            {
                "origin": r.origin.date().isoformat(),
                "day": r.day.date().isoformat(),
                "h": int(r.h),
                "actual": round(float(r.y), 4),
                "forecast": round(float(r.yhat), 4),
                "seasonal_naive": round(float(r.baseline), 4),
            }
            for r in plot.itertuples()
        ],  # fmt: skip
    }


def _overrun_eval(panel: pd.DataFrame, chosen: str, cal: dict, sp: dict) -> dict:
    """Daily origins over validation+test (complete months only); model fitted once at validation start."""
    val_start, _ = sp["validation"]
    _, data_end = sp["test"]
    model = MODEL_FACTORIES[chosen]().fit(panel[panel.day < val_start], "cost_myr")
    daily_total = panel.groupby("day").cost_myr.sum()
    rows = []
    for origin in pd.date_range(val_start, data_end, freq="D"):
        month_end = origin + pd.offsets.MonthEnd(0)
        if month_end > data_end:
            continue  # month not complete in the data: true outcome unknown
        month_start = origin.replace(day=1)
        days = pd.date_range(origin, month_end, freq="D")
        mtd = float(daily_total[(daily_total.index >= month_start) & (daily_total.index < origin)].sum())
        rem = float(model.predict(panel[panel.day < origin], days).yhat.clip(lower=0).sum())
        q, _ = quantile_for(cal["cumulative_total_rel"], len(days))
        actual = float(daily_total[(daily_total.index >= month_start) & (daily_total.index <= month_end)].sum())
        rows.append({"origin": origin, "month": month_start.strftime("%Y-%m"), "days_left": len(days),
                     "predicted": mtd + rem, "lower": mtd + rem * (1 - q), "upper": mtd + rem * (1 + q),
                     "actual": actual})  # fmt: skip
    if not rows:
        return {"status": "insufficient_data", "n_origins": 0}
    df = pd.DataFrame(rows)
    by_budget = {}
    for b in BUDGETS_MYR:
        truth = df.actual > b
        by_budget[f"{b:.0f}"] = {
            "positives": int(truth.sum()),
            "negatives": int((~truth).sum()),
            "central_forecast": classification_report(truth, df.predicted > b),
            "high_confidence_lower_bound": classification_report(truth, df.lower > b),
            "possible_upper_bound": classification_report(truth, df.upper > b),
        }
    ape = (df.predicted - df.actual).abs() / df.actual
    return {
        "status": "ok",
        "model": chosen,
        "frozen_at": val_start.date().isoformat(),
        "n_origins": len(df),
        "months": {m: round(float(a), 2) for m, a in df.groupby("month").actual.first().items()},
        "budgets": by_budget,
        "month_end_abs_pct_error": {
            "all": float(ape.mean()),
            "days_left_gt_14": float(ape[df.days_left > 14].mean()) if (df.days_left > 14).any() else None,
            "days_left_le_14": float(ape[df.days_left <= 14].mean()) if (df.days_left <= 14).any() else None,
        },
        "month_end_interval_coverage": float(((df.actual >= df.lower) & (df.actual <= df.upper)).mean()),
        "caveat": "Few distinct months; origins within a month are highly correlated. Treat as indicative.",
    }


# --------------------------------------------------------------------------- anomalies


def day_labels(features: pd.DataFrame, truth: pd.DataFrame) -> pd.Series:
    """'positive' | 'drift' | 'benign' | 'negative' for every (app, day)."""
    label = pd.Series("negative", index=features.index, dtype=object)
    for ev in truth[truth.kind != "A8"].itertuples():
        mask = (features.app_id == ev.app_id) & features.day.between(
            pd.Timestamp(ev.start_date), pd.Timestamp(ev.end_date)
        )
        label[mask] = {"yes": "positive", "drift": "drift", "no": "benign"}[ev.alert_expected]
    return label


def _metrics_for(pred: pd.DataFrame, labels: pd.Series, truth: pd.DataFrame, lo, hi) -> dict:
    in_split = pred.day.between(lo, hi) & pred.warm
    lab = labels[in_split]
    usable = lab.isin(["positive", "negative", "benign"])  # drift days excluded from day-level scoring
    day = classification_report((lab[usable] == "positive"), pred.alert[in_split][usable])
    n_days = (hi - lo).days + 1

    alerts = merge_alert_days(pred[in_split])
    windows = truth[(truth.kind != "A8") & truth.alert_expected.isin(["yes", "drift"])]

    def overlaps(a) -> bool:
        return any(
            (w.app_id == a.app_id) and (pd.Timestamp(w.start_date) <= a.end)
            and (pd.Timestamp(w.end_date) + pd.Timedelta(days=1 if w.alert_expected == "yes" else 7)
                 >= a.start)
            for w in windows.itertuples()
        )  # fmt: skip

    false_alerts = int(sum(not overlaps(a) for a in alerts.itertuples())) if len(alerts) else 0
    events = []
    split_truth = truth[(truth.kind != "A8") & pd.to_datetime(truth.start_date).between(lo, hi)]
    for ev in split_truth.itertuples():
        start, end = pd.Timestamp(ev.start_date), pd.Timestamp(ev.end_date)
        slack = 7 if ev.alert_expected == "drift" else 0
        hits = pred[(pred.app_id == ev.app_id) & pred.day.between(start, end + pd.Timedelta(days=slack)) & pred.alert]
        if ev.alert_expected == "drift":  # an outage alert is not evidence of detecting cost drift
            hits = hits[hits.reason_code != "outage"]
        first = hits.day.min() if len(hits) else None
        events.append({
            "event_id": ev.event_id, "kind": ev.kind, "app_id": ev.app_id,
            "alert_expected": ev.alert_expected,
            "start_date": ev.start_date, "detected": first is not None,
            "detection_delay_days": int((first - start).days) if first is not None else None,
            "reason_codes": sorted(set(hits.reason_code.dropna())),
        })  # fmt: skip
    ev_df = pd.DataFrame(events)
    expected = ev_df[ev_df.alert_expected == "yes"] if len(ev_df) else ev_df
    benign = ev_df[ev_df.alert_expected == "no"] if len(ev_df) else ev_df
    delays = expected[expected.detected].detection_delay_days if len(expected) else pd.Series(dtype=float)
    return {
        "days": n_days,
        "day_level": day,
        "confusion_matrix": {"tp": day["tp"], "fp": day["fp"], "fn": day["fn"], "tn": day["tn"]},
        "alert_events": len(alerts),
        "false_alert_events": false_alerts,
        "false_alerts_per_30_days": false_alerts / n_days * 30,
        "event_recall": float(expected.detected.mean()) if len(expected) else None,
        "mean_detection_delay_days": float(delays.mean()) if len(delays) else None,
        "benign_promotions": {
            "total": len(benign),
            "alerted": int(benign.detected.sum()) if len(benign) else 0,
        },
        "events": events,
    }


def evaluate_anomaly(daily: pd.DataFrame, truth: pd.DataFrame, manifest: dict) -> dict:
    sp = _split_days(manifest)
    scored = score_days(app_day_features(daily))
    labels = day_labels(scored, truth)
    train_lo, train_hi = sp["train"]
    base = AnomalyDetector(DetectorConfig()).fit(scored[scored.day.between(train_lo, train_hi)])

    sweep = []
    for z, q in itertools.product(Z_GRID, IF_GRID):
        det = base.with_config(DetectorConfig(z_threshold=z, if_quantile=q))
        m = _metrics_for(det.predict(scored), labels, truth, *sp["validation"])
        sweep.append({"z_threshold": z, "if_quantile": q, "precision": m["day_level"]["precision"],
                      "recall": m["day_level"]["recall"], "f1": m["day_level"]["f1"],
                      "false_alerts_per_30_days": m["false_alerts_per_30_days"]})  # fmt: skip
    best = max(sweep, key=lambda r: ((r["f1"] or 0.0), -r["false_alerts_per_30_days"], r["z_threshold"]))
    chosen = DetectorConfig(z_threshold=best["z_threshold"], if_quantile=best["if_quantile"])
    det = base.with_config(chosen)
    pred = det.predict(scored)
    per_split = {name: _metrics_for(pred, labels, truth, lo, hi) for name, (lo, hi) in sp.items()}

    benign_all = truth[truth.alert_expected == "no"]
    benign_alerted = sum(
        bool(pred[(pred.app_id == b.app_id) & (pred.day == pd.Timestamp(b.start_date)) & pred.alert].shape[0])
        for b in benign_all.itertuples()
    )
    return {
        "unit": "application-day",
        "data_origin": "synthetic",
        "methods": ["robust same-weekday median/MAD z-score", "IsolationForest on deviation features"],
        "chosen_config": config_dict(chosen),
        "if_threshold_score": det.if_threshold,
        "selected_on": "validation (max day-level F1, ties -> fewer false alerts)",
        "threshold_sweep_validation": sweep,
        "splits": per_split,
        "benign_promotions_all_splits": {"total": len(benign_all), "alerted": benign_alerted},
        "notes": [
            "Drift (A6) days are excluded from day-level precision/recall; drift detection is reported "
            "per event (outage alerts do not count as detecting drift).",
            "Benign promotion days (A7) count as negatives (hard negatives).",
            "Injected labels are used only for scoring, never as features.",
        ],
    }


def summarize(forecast: dict, anomaly: dict) -> dict:
    fc_test = forecast["test"]["scores"]
    an_test = anomaly["splits"]["test"]
    return {
        "forecast_model": forecast["selection"]["chosen"],
        "forecast_test_workspace_wape": {m: s["workspace_daily"]["wape"] for m, s in fc_test.items()},
        "forecast_test_interval_coverage": forecast["test"]["interval_coverage"],
        "anomaly_test_precision": an_test["day_level"]["precision"],
        "anomaly_test_recall": an_test["day_level"]["recall"],
        "anomaly_test_event_recall": an_test["event_recall"],
        "anomaly_test_false_alerts_per_30_days": an_test["false_alerts_per_30_days"],
    }


def evaluate_simulator(daily: pd.DataFrame, scenario_truth: pd.DataFrame, manifest: dict, model: str) -> dict:
    """What-if estimate vs the synthetic counterfactual truth over the test window.

    'forecast' uses the simulator exactly as in production (forecast units from history before the
    test window); 'oracle' feeds actual units to isolate assumption error from forecast error.
    """
    from app.ml.train_forecast import fit_predict
    from app.services.simulator import Assumptions, simulate_frame

    panel = segment_panel(daily)
    start, end = (pd.Timestamp(x) for x in manifest["splits"]["test"])
    days = pd.date_range(start, end, freq="D")
    hist = panel[panel.day < start]
    cost = fit_predict(model, hist, "cost_myr", days)
    req = fit_predict(model, hist, "requests", days).rename(columns={"yhat": "requests"})
    pts = cost.rename(columns={"yhat": "cost"}).merge(req, on=["day", "app_id", "request_category"])
    pts = pts.rename(columns={"app_id": "app"})
    actual = panel[panel.day.between(start, end)].rename(columns={"app_id": "app", "cost_myr": "cost"})
    assume = manifest["assumptions"]
    a = Assumptions(
        eligible_share=assume["faq_eligible_share_of_static_faq"],
        safe_hit_rate=sum(s * r for s, r in assume["paraphrase_mix_and_matcher_recall"].values()),
        overhead_per_lookup_myr=assume["cache_overhead_per_lookup_myr"],
        fixed_daily_myr=assume["cache_fixed_daily_myr"],
        target_apps=list(manifest["applications"]), sources={}, samples={},
    )  # fmt: skip
    est, oracle = simulate_frame(pts, a), simulate_frame(actual, a)
    st = scenario_truth.assign(day=pd.to_datetime(scenario_truth.day))
    st = st[st.day.between(start, end)]
    true_net = float(st.true_net_savings_myr.sum())

    def err(x: float) -> dict:
        return {"estimate_myr": round(x, 4), "abs_error_myr": round(abs(x - true_net), 4),
                "pct_error": abs(x - true_net) / abs(true_net) if true_net else None}  # fmt: skip

    return {
        "window": [str(start.date()), str(end.date())],
        "true_net_savings_myr": round(true_net, 4),
        "true_gross_avoided_myr": round(float(st.avoided_cost_myr.sum()), 4),
        "true_overhead_myr": round(float(st.overhead_myr.sum()), 4),
        "forecast_based": err(est["net_savings_myr"]),
        "oracle_actual_units": err(oracle["net_savings_myr"]),
        "assumptions": {"eligible_share": a.eligible_share, "safe_hit_rate": round(a.safe_hit_rate, 4)},
        "note": "Assumptions are the generator's true rates (synthetic); with real traffic they must be measured.",
    }


def evaluate_all(
    daily: pd.DataFrame, truth: pd.DataFrame, manifest: dict, scenario_truth: pd.DataFrame | None = None
) -> dict:
    from app.ml.cache_eval import evaluate_cache

    fc = evaluate_forecast(daily, manifest, truth)
    an = evaluate_anomaly(daily, truth, manifest)
    cache = evaluate_cache()
    sim = (
        evaluate_simulator(daily, scenario_truth, manifest, fc["selection"]["chosen"])
        if scenario_truth is not None
        else None
    )
    summary = summarize(fc, an)
    summary.update({
        "cache_hit_precision": cache["hit_precision"], "cache_false_hits": cache["false_hits"],
        "cache_positive_coverage": cache["positive_coverage"],
        "simulator_forecast_based_pct_error": sim["forecast_based"]["pct_error"] if sim else None,
    })  # fmt: skip
    return {
        "dataset": {k: manifest[k] for k in ("generator_version", "seed", "days", "start_date", "end_date", "splits")},
        "data_origin": "synthetic",
        "forecast": fc,
        "anomaly": an,
        "cache": cache,
        "simulator": sim,
        "summary": summary,
    }


def json_safe(obj):
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [json_safe(v) for v in obj]
    if isinstance(obj, np.integer | np.bool_):
        return obj.item()
    if isinstance(obj, np.floating):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, float) and np.isnan(obj):
        return None
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat()
    return obj
