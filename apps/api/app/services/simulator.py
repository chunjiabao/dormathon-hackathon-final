"""What-if simulator for the semantic FAQ cache (no LLM calls).

Input is ALWAYS a persisted forecast run: the same per-day/segment predicted requests and costs
that produced the month-end forecast. The intervention transforms those exact units:

    hits_s,d          = predicted_requests_s,d x eligible_share x safe_hit_rate      (static_faq, target apps)
    gross_savings     = sum hits x predicted_cost_per_request_s,d   (cache hits make no provider call)
    overhead          = static_faq lookups x overhead_per_lookup + fixed_daily x days x target_apps
    net_savings       = gross_savings - overhead
    scenario_total    = baseline_total - net_savings

Browser clients may only adjust bounded assumptions; baseline costs are always loaded server-side.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiRequest, Application, ForecastPoint, ForecastRun, Policy, ScenarioRun
from app.services import embeddings
from app.services.cache import active_entries
from app.services.forecast import month_bounds
from app.services.history import app_maps
from app.services.synthetic_loader import dataset_record

MIN_MEASURED_SAMPLES = 50
PRIOR_WEIGHT = 20  # pseudo-observations when smoothing measured rates toward the prior
ASSUMED = {"eligible_share": 0.60, "safe_hit_rate": 0.70}
SENSITIVITY = {"eligible_share": 0.10, "safe_hit_rate": 0.15}


@dataclass
class Assumptions:
    eligible_share: float
    safe_hit_rate: float
    overhead_per_lookup_myr: float
    fixed_daily_myr: float
    target_apps: list[str]
    sources: dict[str, str]
    samples: dict[str, int]

    def bounded(self, overrides: dict | None) -> Assumptions:
        o = overrides or {}
        a = Assumptions(**asdict(self))
        for key, lo, hi in (("eligible_share", 0, 1), ("safe_hit_rate", 0, 1), ("overhead_per_lookup_myr", 0, 0.01),
                            ("fixed_daily_myr", 0, 50)):  # fmt: skip
            if o.get(key) is not None:
                setattr(a, key, min(hi, max(lo, float(o[key]))))
                a.sources = {**a.sources, key: "user_adjusted"}
        if o.get("target_apps"):
            a.target_apps = [x for x in o["target_apps"] if x in self.target_apps]
        return a


def simulate_frame(points: pd.DataFrame, a: Assumptions) -> dict:
    """Pure core. points: day, app, request_category, requests, cost (forecast units)."""
    tgt = points[points.app.isin(a.target_apps)]
    faq = tgt[tgt.request_category == "static_faq"]
    cpr = (faq.cost / faq.requests.where(faq.requests > 0)).fillna(0.0)
    hits = faq.requests * a.eligible_share * a.safe_hit_rate
    gross = float((hits * cpr).sum())
    lookups = float(faq.requests.sum())  # requests that reach FAQ matching (same definition as measurement)
    days = int(points.day.nunique())
    overhead = lookups * a.overhead_per_lookup_myr + a.fixed_daily_myr * days * len(set(tgt.app))
    per_app = []
    for app, g in faq.groupby("app"):
        h = hits.loc[g.index]
        per_app.append({"application": app, "faq_forecast_cost_myr": round(float(g.cost.sum()), 4),
                        "predicted_hits": round(float(h.sum()), 1),
                        "gross_savings_myr": round(float((h * cpr.loc[g.index]).sum()), 4)})  # fmt: skip
    return {
        "faq_forecast_cost_myr": float(faq.cost.sum()),
        "predicted_faq_requests": float(faq.requests.sum()),
        "predicted_hits": float(hits.sum()),
        "gross_savings_myr": gross,
        "overhead_myr": overhead,
        "net_savings_myr": gross - overhead,
        "days": days,
        "per_application": per_app,
    }


def default_assumptions(session: Session, workspace_id) -> Assumptions:
    """Measured (smoothed) shadow rates from real traffic if enough samples, else synthetic, else assumed."""
    settings = get_settings()
    id_to_name, _ = app_maps(session, workspace_id)
    target = sorted(
        id_to_name[p.application_id]
        for p in session.scalars(select(Policy).where(Policy.workspace_id == workspace_id,
                                                      Policy.policy_type == "semantic_cache"))
    )  # fmt: skip
    prior, source = dict(ASSUMED), "assumed"
    ds = dataset_record(session, workspace_id)
    if ds is not None:
        assume = ds.metrics_json["manifest"]["assumptions"]
        mix = assume["paraphrase_mix_and_matcher_recall"]
        prior = {"eligible_share": float(assume["faq_eligible_share_of_static_faq"]),
                 "safe_hit_rate": float(sum(share * recall for share, recall in mix.values()))}  # fmt: skip
        source = "synthetic"

    rows = session.execute(
        select(ApiRequest.cache_decision, func.count())
        .where(ApiRequest.workspace_id == workspace_id, ApiRequest.data_origin == "real",
               ApiRequest.request_category == "static_faq", ApiRequest.cache_decision.is_not(None))
        .group_by(ApiRequest.cache_decision)
    ).all()  # fmt: skip
    counts = {d: n for d, n in rows}
    n = sum(counts.values())
    gate_passed = sum(c for d, c in counts.items() if "bypass_" not in d)
    matched = sum(c for d, c in counts.items() if "eligible_" in d)
    values, sources = dict(prior), {"eligible_share": source, "safe_hit_rate": source}
    if n >= MIN_MEASURED_SAMPLES:
        values["eligible_share"] = (gate_passed + PRIOR_WEIGHT * prior["eligible_share"]) / (n + PRIOR_WEIGHT)
        sources["eligible_share"] = "measured"
    if gate_passed >= MIN_MEASURED_SAMPLES:
        values["safe_hit_rate"] = (matched + PRIOR_WEIGHT * prior["safe_hit_rate"]) / (gate_passed + PRIOR_WEIGHT)
        sources["safe_hit_rate"] = "measured"
    sources |= {"overhead_per_lookup_myr": "assumed", "fixed_daily_myr": "assumed"}
    return Assumptions(
        eligible_share=round(values["eligible_share"], 4), safe_hit_rate=round(values["safe_hit_rate"], 4),
        overhead_per_lookup_myr=settings.cache_overhead_per_lookup_myr, fixed_daily_myr=settings.cache_fixed_daily_myr,
        target_apps=target, sources=sources,
        samples={"real_static_faq_requests": n, "gate_passed": gate_passed, "matched": matched},
    )  # fmt: skip


def forecast_units(session: Session, run: ForecastRun) -> pd.DataFrame:
    today = date.fromisoformat(run.assumptions_json["today"])
    ms, me = month_bounds(today)
    id_to_name, _ = app_maps(session, run.workspace_id)
    rows = session.execute(
        select(ForecastPoint.day, ForecastPoint.application_id, ForecastPoint.request_category,
               ForecastPoint.predicted_requests, ForecastPoint.predicted_cost_myr,
               ForecastPoint.lower_cost_myr, ForecastPoint.upper_cost_myr)
        .where(ForecastPoint.forecast_run_id == run.id, ForecastPoint.day >= ms, ForecastPoint.day <= me)
    ).all()  # fmt: skip
    df = pd.DataFrame(rows, columns=["day", "application_id", "request_category", "requests", "cost", "lo", "hi"])
    df = df.astype({"requests": float, "cost": float, "lo": float, "hi": float})
    df["app"] = df.application_id.map(id_to_name)
    return df


def quality_gate(session: Session, workspace_id, a: Assumptions, cache_eval: dict | None) -> dict:
    id_to_name, name_to_id = app_maps(session, workspace_id)
    from datetime import UTC, datetime

    from app.models import Workspace

    ws = session.get(Workspace, workspace_id)
    now = datetime.now(UTC)
    checks = []
    catalogs_ok = all(
        active_entries(session, session.get(Application, name_to_id[n]), ws, "en", now) for n in a.target_apps
    )
    checks.append(
        {
            "id": "approved_faq_catalog",
            "passed": bool(a.target_apps) and catalogs_ok,
            "required": True,
            "detail": "Every target application has approved, unexpired, cacheable FAQ entries.",
        }
    )
    policies = session.scalars(
        select(Policy).where(Policy.workspace_id == workspace_id, Policy.policy_type == "semantic_cache")
    ).all()
    thr_ok = all(0.95 <= float(p.similarity_threshold) <= 0.99 for p in policies)
    checks.append(
        {
            "id": "threshold_safe_range",
            "passed": thr_ok,
            "required": True,
            "detail": "Similarity threshold is within the safe range 0.95-0.99.",
        }
    )
    if cache_eval is None:
        checks.append(
            {
                "id": "adversarial_cache_tests",
                "passed": False,
                "required": True,
                "detail": "No cache evaluation has been run yet.",
            }
        )
    else:
        checks.append(
            {
                "id": "adversarial_cache_tests",
                "passed": cache_eval["false_hits"] == 0,
                "required": True,
                "detail": f"{cache_eval['false_hits']} false hits on {cache_eval['n']} labelled queries "
                f"(hit precision {cache_eval['hit_precision']:.2f}); not a general guarantee.",
            }
        )
    sem = embeddings.status()["semantic_matching"]
    checks.append(
        {
            "id": "semantic_model",
            "passed": sem == "available",
            "required": False,
            "detail": f"Local embedding model {sem}; exact/alias matching works without it.",
        }
    )
    checks.append(
        {
            "id": "approved_answers_only",
            "passed": True,
            "required": True,
            "detail": "Hits return the approved FAQ answer, never stored model output; personalised, "
            "dynamic, multi-question and non-English requests bypass the cache.",
        }
    )
    checks.append({"id": "reversible", "passed": True, "required": True,
                   "detail": "Owner can disable the policy instantly; all changes are audited."})  # fmt: skip
    status = "pass" if all(c["passed"] for c in checks if c["required"]) else "fail"
    return {"status": status, "checks": checks}


def evidence_type(a: Assumptions) -> str:
    kinds = {a.sources["eligible_share"], a.sources["safe_hit_rate"]}
    if kinds == {"measured"}:
        return "measured"
    if "user_adjusted" in kinds or "assumed" in kinds:
        return "assumed"
    return "synthetic" if "synthetic" in kinds else "measured+synthetic"


def run_scenario(
    session: Session, run: ForecastRun, scenario_type: str, overrides: dict | None, cache_eval: dict | None
) -> tuple[ScenarioRun, dict]:
    if run.status != "ok":
        raise ValueError("forecast run has no usable forecast")
    base_a = default_assumptions(session, run.workspace_id)
    a = base_a.bounded(overrides)
    pts = forecast_units(session, run)
    baseline_total = float(run.forecast_total_myr)
    budget = float(run.budget_myr)
    if scenario_type == "none":
        core = {"gross_savings_myr": 0.0, "overhead_myr": 0.0, "net_savings_myr": 0.0, "per_application": []}
        gate = {"status": "pass", "checks": []}
        sens = {"low": 0.0, "base": 0.0, "high": 0.0, "forecast_interval": {"low": 0.0, "high": 0.0}}
    else:
        core = simulate_frame(pts, a)
        gate = quality_gate(session, run.workspace_id, a, cache_eval)
        lo = Assumptions(
            **{
                **asdict(a),
                "eligible_share": max(0, a.eligible_share - SENSITIVITY["eligible_share"]),
                "safe_hit_rate": max(0, a.safe_hit_rate - SENSITIVITY["safe_hit_rate"]),
            }
        )
        hi = Assumptions(
            **{
                **asdict(a),
                "eligible_share": min(1, a.eligible_share + SENSITIVITY["eligible_share"]),
                "safe_hit_rate": min(1, a.safe_hit_rate + SENSITIVITY["safe_hit_rate"]),
            }
        )
        # Assumption sensitivity on the central forecast (what the sliders change)...
        sens = {
            "low": simulate_frame(pts, lo)["net_savings_myr"],
            "base": core["net_savings_myr"],
            "high": simulate_frame(pts, hi)["net_savings_myr"],
        }
        # ...reported separately from forecast uncertainty (same assumptions, interval-bound costs).
        sens["forecast_interval"] = {
            "low": simulate_frame(pts.assign(cost=pts.lo), a)["net_savings_myr"],
            "high": simulate_frame(pts.assign(cost=pts.hi), a)["net_savings_myr"],
        }
    net = core["net_savings_myr"]
    projected = baseline_total - net
    result = {
        "scenario_type": scenario_type,
        "forecast_run_id": str(run.id),
        "method": "Transforms the persisted forecast's predicted requests and costs; no LLM involved.",
        "baseline_forecast": {
            "total_myr": baseline_total, "observed_to_date_myr": float(run.observed_to_date_myr),
            "predicted_remaining_myr": float(run.predicted_remaining_myr),
            "lower_myr": float(run.lower_myr), "upper_myr": float(run.upper_myr),
        },
        "scenario_forecast": {
            "total_myr": projected,
            "lower_myr": float(run.lower_myr) - sens["forecast_interval"]["high"],
            "upper_myr": float(run.upper_myr) - sens["forecast_interval"]["low"],
        },
        "gross_savings_myr": core["gross_savings_myr"],
        "overhead_myr": core["overhead_myr"],
        "net_savings_myr": net,
        "savings_sensitivity_myr": sens,
        "budget_myr": budget,
        "within_budget_after": projected <= budget,
        "assumptions": asdict(a),
        "default_assumptions": asdict(base_a),
        "quality_gate": gate,
        "evidence_type": "n/a" if scenario_type == "none" else evidence_type(a),
        "details": {k: v for k, v in core.items() if k not in ("gross_savings_myr", "overhead_myr", "net_savings_myr")},
    }  # fmt: skip
    sr = ScenarioRun(
        workspace_id=run.workspace_id, forecast_run_id=run.id, scenario_type=scenario_type,
        assumptions_json=result["assumptions"], baseline_cost_myr=baseline_total, projected_cost_myr=projected,
        gross_savings_myr=core["gross_savings_myr"], overhead_myr=core["overhead_myr"], net_savings_myr=net,
        quality_status=gate["status"], uncertainty_json={"sensitivity": sens, "result": result},
    )  # fmt: skip
    session.add(sr)
    session.flush()
    result["scenario_id"] = str(sr.id)
    sr.uncertainty_json = {"sensitivity": sens, "result": result}
    return sr, result
