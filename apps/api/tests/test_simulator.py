import pandas as pd
import pytest

from app.models import ForecastRun, Recommendation
from app.services import recommender as rec_service
from app.services.simulator import Assumptions, run_scenario, simulate_frame

GOOD_EVAL = {"false_hits": 0, "n": 51, "hit_precision": 1.0}


def _a(**kw):
    base = dict(eligible_share=0.5, safe_hit_rate=0.8, overhead_per_lookup_myr=0.001, fixed_daily_myr=0.1,
                target_apps=["app1"], sources={"eligible_share": "assumed", "safe_hit_rate": "assumed"},
                samples={})  # fmt: skip
    return Assumptions(**{**base, **kw})


def test_simulate_frame_math_on_toy_forecast():
    pts = pd.DataFrame({
        "day": ["d1", "d1", "d2", "d2", "d1"],
        "app": ["app1", "app1", "app1", "app1", "app2"],
        "request_category": ["static_faq", "other", "static_faq", "other", "static_faq"],
        "requests": [100, 50, 200, 50, 999], "cost": [1.0, 5.0, 2.0, 5.0, 99.0],
    })  # fmt: skip
    r = simulate_frame(pts, _a())
    # hits = 300 x 0.5 x 0.8 = 120 at RM0.01/request -> RM1.20 gross (other categories and app2 untouched)
    assert r["gross_savings_myr"] == pytest.approx(1.2)
    assert r["overhead_myr"] == pytest.approx(300 * 0.001 + 0.1 * 2 * 1)
    assert r["net_savings_myr"] == pytest.approx(1.2 - 0.5)
    assert r["gross_savings_myr"] <= r["faq_forecast_cost_myr"]  # never more than the FAQ cost itself


def test_assumption_overrides_are_bounded():
    a = _a().bounded({"eligible_share": 5, "safe_hit_rate": -1, "target_apps": ["evil"]})
    assert a.eligible_share == 1 and a.safe_hit_rate == 0 and a.target_apps == []
    assert a.sources["eligible_share"] == "user_adjusted"


def test_baseline_is_identical_to_persisted_forecast(seeded, session):
    run = session.get(ForecastRun, seeded["run_id"])
    _, none = run_scenario(session, run, "none", None, GOOD_EVAL)
    _, cache = run_scenario(session, run, "semantic_cache", None, GOOD_EVAL)
    for r in (none, cache):
        assert r["baseline_forecast"]["total_myr"] == float(run.forecast_total_myr)
    assert none["net_savings_myr"] == 0 and none["scenario_forecast"]["total_myr"] == float(run.forecast_total_myr)
    assert cache["scenario_forecast"]["total_myr"] == pytest.approx(
        float(run.forecast_total_myr) - cache["net_savings_myr"]
    )
    assert cache["gross_savings_myr"] <= cache["details"]["faq_forecast_cost_myr"]
    s = cache["savings_sensitivity_myr"]
    assert s["low"] <= s["base"] <= s["high"] and "forecast_interval" in s
    assert cache["evidence_type"] == "synthetic"  # defaults come from the synthetic dataset, labelled as such
    assert cache["quality_gate"]["status"] == "pass"
    session.rollback()


def test_quality_failure_blocks_recommendation(seeded, session, monkeypatch):
    monkeypatch.setattr(rec_service, "cache_evaluation", lambda s: {"false_hits": 2, "n": 51, "hit_precision": 0.9})
    rec = rec_service.recommend(session, session.get(ForecastRun, seeded["run_id"]))
    assert rec.action_type == "no_action"
    assert rec.rationale.startswith("No safe intervention yet; collect more data.")
    assert "adversarial_cache_tests" in rec.rationale


def test_negative_net_savings_blocks_recommendation(seeded, session, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(rec_service, "cache_evaluation", lambda s: GOOD_EVAL)
    monkeypatch.setattr(get_settings(), "cache_fixed_daily_myr", 50.0)  # overhead dwarfs savings
    rec = rec_service.recommend(session, session.get(ForecastRun, seeded["run_id"]))
    assert rec.action_type == "no_action" and "net savings" in rec.rationale


def test_positive_case_rationale_is_honest_about_budget(seeded, session, monkeypatch):
    monkeypatch.setattr(rec_service, "cache_evaluation", lambda s: GOOD_EVAL)
    run = session.get(ForecastRun, seeded["run_id"])
    rec = rec_service.recommend(session, run)
    assert rec.action_type == "enable_semantic_cache" and rec.status == "proposed"
    assert f"RM{float(run.forecast_total_myr):.2f}" in rec.rationale
    _, result = run_scenario(session, run, "semantic_cache", None, GOOD_EVAL)
    if result["scenario_forecast"]["total_myr"] > float(run.budget_myr):
        assert "does not fully eliminate the budget overrun" in rec.rationale
    assert isinstance(rec, Recommendation)


def test_compare_endpoint_ignores_client_supplied_costs(client, owner_headers, seeded):
    base = client.post("/api/v1/scenarios/compare", json={"actions": ["semantic_cache"]}, headers=owner_headers).json()
    forged = client.post(
        "/api/v1/scenarios/compare",
        json={"actions": ["semantic_cache"], "baseline_cost_myr": 1, "forecast_total_myr": 1,
              "assumptions": {"baseline_cost_myr": 1}},
        headers=owner_headers,
    ).json()  # fmt: skip
    a, b = base["scenarios"][0], forged["scenarios"][0]
    assert a["baseline_forecast"] == b["baseline_forecast"] and a["net_savings_myr"] == b["net_savings_myr"]


def test_compare_endpoint_applies_slider_assumptions(client, viewer_headers, seeded):
    def run(rate):
        body = {"actions": ["semantic_cache"], "assumptions": {"safe_hit_rate": rate}}
        return client.post("/api/v1/scenarios/compare", json=body, headers=viewer_headers).json()["scenarios"][0]

    low, high = run(0.2), run(0.9)
    assert high["gross_savings_myr"] > low["gross_savings_myr"]
    assert high["evidence_type"] == "assumed"
    bad = {"actions": ["semantic_cache"], "assumptions": {"safe_hit_rate": 2}}
    assert client.post("/api/v1/scenarios/compare", json=bad, headers=viewer_headers).status_code == 422
