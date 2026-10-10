"""Deterministic recommendation from the persisted forecast + simulated scenarios (no LLM).

Only interventions that pass the quality gate AND have positive net savings are eligible; the one
with the highest net savings is proposed. Otherwise the recommendation is explicitly
"No safe intervention yet; collect more data" (a valid decision). Rationale text is a fixed
template filled with measured/forecast numbers, and never claims the budget is met when it is not.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ForecastRun, Policy, PolicyAudit, Recommendation, ScenarioRun
from app.services.evaluation import cache_evaluation
from app.services.history import app_maps
from app.services.simulator import run_scenario

CANDIDATES = ("semantic_cache",)
SOURCE_WORDS = {"measured": "measured", "synthetic": "synthetic-data", "assumed": "assumed",
                "user_adjusted": "user-adjusted", "measured+synthetic": "partly measured"}  # fmt: skip


class ApprovalError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _rationale(result: dict) -> str:
    b = result["baseline_forecast"]["total_myr"]
    budget = result["budget_myr"]
    a = result["assumptions"]
    faq_cost = result["details"]["faq_forecast_cost_myr"]
    hit_share = a["eligible_share"] * a["safe_hit_rate"]
    src = SOURCE_WORDS.get(result["evidence_type"], result["evidence_type"])
    apps = ", ".join(a["target_apps"])
    text = (
        f"Projected month-end spending is RM{b:.2f} against a RM{budget:.2f} budget. Static FAQ traffic in "
        f"{apps} contributes RM{faq_cost:.2f} of the remaining forecast. With a {src} {hit_share:.0%} safe "
        f"cache-hit share and RM{result['overhead_myr']:.2f} estimated overhead, enabling approved FAQ caching "
        f"could reduce the forecast to approximately RM{result['scenario_forecast']['total_myr']:.2f} "
        f"(net saving RM{result['net_savings_myr']:.2f}; RM{result['savings_sensitivity_myr']['low']:.2f}"
        f" to RM{result['savings_sensitivity_myr']['high']:.2f} if hit rates are lower or higher than assumed)."
    )
    if b <= budget:
        text += " The forecast is already within budget; this is an efficiency saving, not a budget fix."
    elif result["within_budget_after"]:
        text += " This would bring the central forecast within budget, subject to the stated assumptions."
    else:
        text += " This does not fully eliminate the budget overrun; monitor after activation."
    return (
        text + " Selected because it is the only evaluated intervention that passes the quality gate"
        " with positive net savings."
    )


def recommend(session: Session, run: ForecastRun) -> Recommendation:
    if run.status != "ok":
        raise ApprovalError(409, "forecast_unavailable", "Run a forecast with sufficient history first.")
    cache_eval = cache_evaluation(session)
    run_scenario(session, run, "none", None, cache_eval)
    options = []
    for kind in CANDIDATES:
        sr, result = run_scenario(session, run, kind, None, cache_eval)
        options.append((sr, result))
    viable = [(sr, r) for sr, r in options if r["quality_gate"]["status"] == "pass" and r["net_savings_myr"] > 0]
    if viable:
        sr, result = max(viable, key=lambda x: x[1]["net_savings_myr"])
        rec = Recommendation(
            workspace_id=run.workspace_id, forecast_run_id=run.id, scenario_run_id=sr.id,
            action_type="enable_semantic_cache", rationale=_rationale(result), status="proposed",
        )  # fmt: skip
    else:
        reasons = []
        for sr, r in options:
            failed = [c["id"] for c in r["quality_gate"]["checks"] if c["required"] and not c["passed"]]
            if failed:
                reasons.append(f"{sr.scenario_type}: quality gate failed ({', '.join(failed)})")
            elif r["net_savings_myr"] <= 0:
                reasons.append(f"{sr.scenario_type}: net savings RM{r['net_savings_myr']:.2f} after overhead")
        rec = Recommendation(
            workspace_id=run.workspace_id, forecast_run_id=run.id,
            scenario_run_id=options[0][0].id if options else None,
            action_type="no_action",
            rationale="No safe intervention yet; collect more data. " + "; ".join(reasons) + ".",
            status="proposed",
        )  # fmt: skip
    session.add(rec)
    session.commit()
    return rec


def latest_forecast_id(session: Session, workspace_id):
    return session.scalar(
        select(ForecastRun.id).where(ForecastRun.workspace_id == workspace_id).order_by(ForecastRun.generated_at.desc())
    )


def target_policies(session: Session, rec: Recommendation) -> list[Policy]:
    sr = session.get(ScenarioRun, rec.scenario_run_id) if rec.scenario_run_id else None
    names = (sr.assumptions_json or {}).get("target_apps", []) if sr else []
    _, name_to_id = app_maps(session, rec.workspace_id)
    ids = [name_to_id[n] for n in names if n in name_to_id]
    return list(session.scalars(select(Policy).where(Policy.application_id.in_(ids),
                                                     Policy.policy_type == "semantic_cache")))  # fmt: skip


def policy_state(p: Policy) -> dict:
    return {"enabled": p.enabled, "similarity_threshold": float(p.similarity_threshold), "ttl_hours": p.ttl_hours,
            "faq_only": p.faq_only, "holdout_enabled": p.holdout_enabled, "version": p.version}  # fmt: skip


def approve(session: Session, rec: Recommendation, actor, expected_version: int, holdout: bool) -> Recommendation:
    """Owner approval: transactionally enable target policies + update recommendation + audit."""
    if rec.status == "enabled":
        return rec  # idempotent: already approved and enabled, no duplicate audit
    if rec.status != "proposed":
        raise ApprovalError(409, "invalid_state", f"Recommendation is {rec.status}.")
    if rec.version != expected_version:
        raise ApprovalError(409, "version_conflict", "Recommendation changed; reload before approving.")
    if rec.forecast_run_id != latest_forecast_id(session, rec.workspace_id):
        raise ApprovalError(409, "stale", "A newer forecast exists; regenerate the recommendation.")
    if rec.action_type != "enable_semantic_cache":
        raise ApprovalError(400, "nothing_to_approve", "This recommendation does not propose an action.")
    now = datetime.now(UTC)
    for p in target_policies(session, rec):
        old = policy_state(p)
        p.enabled, p.approved_by, p.approved_at, p.updated_at = True, actor, now, now
        p.holdout_enabled = holdout
        p.version += 1
        session.add(PolicyAudit(workspace_id=p.workspace_id, application_id=p.application_id, actor_user_id=actor,
                                action="policy_enabled", old_value=old,
                                new_value={**policy_state(p), "recommendation_id": str(rec.id)}))  # fmt: skip
    session.add(PolicyAudit(workspace_id=rec.workspace_id, actor_user_id=actor, action="recommendation_approved",
                            old_value={"status": rec.status, "version": rec.version},
                            new_value={"status": "enabled", "version": rec.version + 1}))  # fmt: skip
    rec.status, rec.decided_at, rec.decided_by, rec.version = "enabled", now, actor, rec.version + 1
    session.commit()
    return rec


def reject(session: Session, rec: Recommendation, actor, expected_version: int) -> Recommendation:
    if rec.status == "rejected":
        return rec
    if rec.status != "proposed":
        raise ApprovalError(409, "invalid_state", f"Recommendation is {rec.status}.")
    if rec.version != expected_version:
        raise ApprovalError(409, "version_conflict", "Recommendation changed; reload before rejecting.")
    now = datetime.now(UTC)
    session.add(PolicyAudit(workspace_id=rec.workspace_id, actor_user_id=actor, action="recommendation_rejected",
                            old_value={"status": rec.status}, new_value={"status": "rejected"}))  # fmt: skip
    rec.status, rec.decided_at, rec.decided_by, rec.version = "rejected", now, actor, rec.version + 1
    session.commit()
    return rec


def disable_policy(session: Session, policy: Policy, actor) -> Policy:
    """Emergency disable: provider calls resume immediately for the application."""
    if not policy.enabled:
        return policy
    old = policy_state(policy)
    now = datetime.now(UTC)
    policy.enabled, policy.updated_at, policy.version = False, now, policy.version + 1
    session.add(PolicyAudit(workspace_id=policy.workspace_id, application_id=policy.application_id, actor_user_id=actor,
                            action="policy_disabled", old_value=old, new_value=policy_state(policy)))  # fmt: skip
    for rec in session.scalars(select(Recommendation).where(Recommendation.workspace_id == policy.workspace_id,
                                                            Recommendation.status == "enabled")):  # fmt: skip
        if any(p.id == policy.id for p in target_policies(session, rec)):
            rec.status, rec.version = "disabled", rec.version + 1
    session.commit()
    return policy
