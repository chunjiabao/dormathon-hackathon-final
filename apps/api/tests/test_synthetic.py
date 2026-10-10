import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.ml.clean import mark_retries
from app.ml.synthetic import generate, split_bounds, write


def test_deterministic_for_seed_42(synthetic, tmp_path):
    again = generate(42, 180, date(2026, 10, 9))
    a = write(synthetic, tmp_path / "a")
    b = write(again, tmp_path / "b")
    assert a["files_sha256"] == b["files_sha256"]


def test_different_seed_changes_data(synthetic):
    other = generate(7, 180, date(2026, 10, 9))
    assert not synthetic["daily"].cost_myr.equals(other["daily"].cost_myr)
    # Event schedule (labels and dates) is reproducible regardless of noise seed.
    pd.testing.assert_frame_equal(synthetic["anomaly_truth"], other["anomaly_truth"])


def test_every_row_is_labelled_synthetic(synthetic):
    assert set(synthetic["requests"].data_origin) == {"synthetic"}
    assert set(synthetic["daily"].data_origin) == {"synthetic"}
    assert set(synthetic["scenario_truth"].data_origin) == {"synthetic"}
    assert synthetic["manifest"]["data_origin"] == "synthetic"
    assert "Fully synthetic" in synthetic["manifest"]["disclaimer"]


def test_shape_180_days_3_apps_4_categories(synthetic):
    d = synthetic["daily"]
    assert pd.to_datetime(d.day).nunique() == 180
    assert set(d.app_id) == {"bakery_demo", "tuition_demo", "retail_demo"}
    assert set(d.request_category) == {"static_faq", "order_enquiry", "complex_support", "other"}
    assert (d[["requests", "input_tokens", "output_tokens", "cost_myr"]] >= 0).all().all()


def test_labelled_events_cover_all_types_and_held_out_splits(synthetic):
    t = synthetic["anomaly_truth"]
    events = t[t.kind != "A8"]
    assert len(events) >= 20
    assert set(events.kind) == {"A1", "A2", "A3", "A4", "A5", "A6", "A7"}
    assert set(t[t.kind == "A8"].event_id) == {
        "DQ-missing_values", "DQ-duplicated_rows", "DQ-delayed_records", "DQ-out_of_order", "DQ-extreme_legit"
    }  # fmt: skip
    for split in ("train", "validation", "test"):
        assert (events.split == split).sum() >= 3
    assert {"business_spend", "technical_fault", "operational_outage", "benign"} <= set(events.event_class)
    promos = events[events.kind == "A7"]
    assert all(pd.Timestamp(d).dayofweek >= 5 for d in promos.start_date)  # weekend promotions
    assert set(promos.alert_expected) == {"no"}


def test_split_bounds_are_chronological_70_15_15():
    assert split_bounds(180) == (126, 153)


def test_daily_has_no_label_columns(synthetic):
    forbidden = {"scenario_id", "is_retry", "cache_eligible", "matcher_recognizes", "event_id", "kind"}
    assert not forbidden & set(synthetic["daily"].columns)


def test_injected_mechanisms_are_visible(synthetic):
    req = synthetic["requests"]
    t = synthetic["anomaly_truth"].set_index("event_id")
    a2 = t[t.kind == "A2"].iloc[0]
    in_ev = req[(req.app_id == a2.app_id) & (req.scenario_id == a2.name)]
    base = req[(req.app_id == a2.app_id) & (req.scenario_id == "baseline")]
    ratio = in_ev.input_tokens.median() / base.input_tokens.median()
    assert 2.5 < ratio < 6  # 4x prompt bloat (category mix shifts the median a little)
    a4 = t[t.kind == "A4"].iloc[0]
    retries = req[(req.scenario_id == a4.name)]
    assert 0.2 < retries.is_retry.mean() < 0.35  # 35% of originals retried -> ~26% of all rows


def test_data_quality_defects_detected_and_repaired(synthetic):
    dq = synthetic["manifest"]["data_quality"]
    assert dq["duplicates_removed"] == dq["injected_duplicate_rows"] > 0
    assert dq["missing_output_imputed"] == dq["injected_missing_output_rows"] > 0
    assert dq["delayed_over_1h_rows"] == dq["injected_delayed_rows"] > 0
    assert dq["out_of_order_rows"] > 0
    assert dq["extreme_legit_rows_kept"] == dq["injected_extreme_legit_rows"] > 0


def test_cost_derived_from_tokens_and_versioned_rates(synthetic):
    rates = {
        m["model"]: (m["input_usd_per_million"], m["output_usd_per_million"])
        for m in json.loads(open("app/fixtures/pricing.json").read())["models"]
    }
    r = synthetic["requests"].dropna(subset=["output_tokens"]).head(500)
    expected = [
        round((i * rates[m][0] + o * rates[m][1]) / 1e6 * 4.70, 8)
        for i, o, m in zip(r.input_tokens, r.output_tokens.astype(int), r.model, strict=True)
    ]
    np.testing.assert_allclose(r.cost_myr.astype(float), expected, rtol=1e-9, atol=1e-9)


def test_retry_detection_uses_client_not_just_message():
    t0 = pd.Timestamp("2026-01-01T10:00:00Z")
    df = pd.DataFrame({
        "app_id": ["a"] * 4, "fingerprint": ["faq1"] * 4,
        "client_fingerprint": ["c1", "c2", "c1", "c3"],
        "occurred_at": [t0, t0 + pd.Timedelta(seconds=5), t0 + pd.Timedelta(seconds=20), t0 + pd.Timedelta(seconds=90)],
    })  # fmt: skip
    # Only c1's repeat within 60 s is a retry; different customers asking the same FAQ are not.
    assert mark_retries(df).tolist() == [False, False, True, False]


def test_scenario_truth_counterfactual_is_consistent(synthetic):
    s = synthetic["scenario_truth"]
    assert (s.true_hits <= s.eligible_requests).all()
    assert (s.eligible_requests <= s.static_faq_requests).all()
    np.testing.assert_allclose(s.true_net_savings_myr, s.avoided_cost_myr - s.overhead_myr, atol=1e-5)


@pytest.mark.parametrize("days", [119])
def test_rejects_too_short_history(days):
    with pytest.raises(ValueError):
        generate(42, days, date(2026, 10, 9))


def test_manifest_records_hashes(tmp_path, synthetic):
    m = write(synthetic, tmp_path)
    for name, digest in m["files_sha256"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
