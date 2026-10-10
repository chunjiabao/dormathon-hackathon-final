import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from app.ml.evaluate import day_labels, evaluate_anomaly
from app.ml.train_anomaly import (
    AnomalyDetector,
    DetectorConfig,
    app_day_features,
    merge_alert_days,
    score_days,
)
from app.models import AnomalyEvent

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-5-20250929"


def _daily(n_days=120, seed=0, edits=None):
    """Simple single-app daily frame with weekly seasonality and small noise."""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2026-01-01", periods=n_days)
    rows = []
    for i, d in enumerate(days):
        req = int(200 * (1.2 if d.dayofweek >= 5 else 1.0) * rng.normal(1, 0.04))
        row = {"day": d, "app_id": "app", "request_category": "static_faq", "model": HAIKU, "requests": req,
               "input_tokens": req * 600, "output_tokens": req * 100, "cost_myr": req * 0.01, "retry_requests": 2,
               "data_origin": "synthetic"}  # fmt: skip
        if edits and i in edits:
            row = edits[i](row)
        rows.append(row)
    return pd.DataFrame(rows)


def _detect(daily, config=None):
    scored = score_days(app_day_features(daily))
    det = AnomalyDetector(config or DetectorConfig(z_threshold=4, if_quantile=1.0)).fit(
        scored[scored.day < "2026-03-15"]
    )
    return det.predict(scored)


def test_clean_series_raises_no_alerts():
    pred = _detect(_daily())
    assert not pred.alert.any()


def test_traffic_spike_detected_with_reason():
    def spike(r):
        return {**r, "requests": r["requests"] * 3, "input_tokens": r["input_tokens"] * 3,
                "output_tokens": r["output_tokens"] * 3, "cost_myr": r["cost_myr"] * 3}  # fmt: skip

    pred = _detect(_daily(edits={100: spike, 101: spike}))
    hit = pred[pred.alert]
    assert set(hit.day.dt.strftime("%m-%d")) == {"04-11", "04-12"}
    assert set(hit.reason_code) == {"traffic_spike"}
    events = merge_alert_days(pred)
    assert len(events) == 1 and events.iloc[0].days == 2  # contiguous days merged


def test_prompt_bloat_and_model_mix_and_retry_reasons():
    def bloat(r):
        return {**r, "input_tokens": r["input_tokens"] * 4, "cost_myr": r["cost_myr"] * 3}

    def retry(r):
        return {**r, "requests": int(r["requests"] * 1.35), "retry_requests": int(r["requests"] * 0.35),
                "cost_myr": r["cost_myr"] * 1.35}  # fmt: skip

    pred = _detect(_daily(edits={90: bloat, 100: retry}))
    reasons = dict(zip(pred[pred.alert].day.dt.day_of_year, pred[pred.alert].reason_code, strict=True))
    assert reasons[91] == "prompt_bloat"
    assert reasons[101] == "retry_storm"

    base = _daily()
    shifted = base.iloc[[95]].assign(model=SONNET, requests=lambda d: (d.requests * 0.6).astype(int),
                                     cost_myr=lambda d: d.cost_myr * 0.6 * 3)  # fmt: skip
    base.loc[95, "requests"] = int(base.loc[95, "requests"] * 0.4)
    base.loc[95, "cost_myr"] = base.loc[95, "cost_myr"] * 0.4
    pred = _detect(pd.concat([base, shifted]))
    assert pred[pred.alert].reason_code.tolist() == ["model_mix_shift"]


def test_outage_is_operational_alert_even_without_cost_impact():
    def outage(r):
        return {**r, "requests": 3, "input_tokens": 1800, "output_tokens": 300, "cost_myr": 0.015}

    pred = _detect(_daily(edits={100: outage}))
    row = pred[pred.alert].iloc[0]
    assert row.reason_code == "outage" and row.outage and not row.cost_alert


def test_small_increase_below_impact_floor_not_alerted():
    def small(r):
        return {**r, "requests": r["requests"] * 3, "cost_myr": 0.2}  # big z but tiny money

    pred = _detect(_daily(edits={100: small}), DetectorConfig(z_threshold=4, if_quantile=1.0, impact_floor_myr=5))
    assert not pred.cost_alert.any()


def test_no_detection_during_warmup():
    def spike(r):
        return {**r, "requests": r["requests"] * 5, "cost_myr": r["cost_myr"] * 5}

    pred = _detect(_daily(edits={5: spike}))
    assert not pred.alert.any()


def test_labels_never_used_as_features(synthetic):
    scored = score_days(app_day_features(synthetic["daily"]))
    assert not {"scenario_id", "event_id", "kind", "alert_expected", "is_retry"} & set(scored.columns)


def test_held_out_evaluation_reports_required_metrics(synthetic):
    r = evaluate_anomaly(synthetic["daily"], synthetic["anomaly_truth"], synthetic["manifest"])
    assert r["selected_on"].startswith("validation")
    test = r["splits"]["test"]
    for key in ("precision", "recall", "f1", "false_positive_rate"):
        assert key in test["day_level"]
    assert {"tp", "fp", "fn", "tn"} == set(test["confusion_matrix"])
    assert "false_alerts_per_30_days" in test and "mean_detection_delay_days" in test
    assert test["benign_promotions"]["total"] >= 1
    assert len(r["threshold_sweep_validation"]) > 10
    # Labels: drift excluded, promotions are hard negatives.
    labels = day_labels(score_days(app_day_features(synthetic["daily"])), synthetic["anomaly_truth"])
    assert {"positive", "drift", "benign", "negative"} == set(labels)


def test_persisted_events_have_explanations_and_no_fake_confidence(seeded, session):
    events = session.scalars(select(AnomalyEvent).where(AnomalyEvent.workspace_id == seeded["workspace_id"])).all()
    assert events
    for e in events:
        assert e.explanation and "not a proven cause" in e.explanation
        assert "%" not in e.explanation.split("expected")[0] or e.metric in ("expensive_share", "retry_rate")
        assert "confidence" not in e.explanation.lower()
        assert e.is_synthetic
        assert e.severity in {"low", "medium", "high"}


@pytest.mark.parametrize("reason", ["outage", "prompt_bloat", "traffic_spike"])
def test_seeded_detection_finds_injected_mechanisms(seeded, session, reason):
    codes = set(
        session.scalars(select(AnomalyEvent.reason_code).where(AnomalyEvent.workspace_id == seeded["workspace_id"]))
    )
    assert reason in codes
