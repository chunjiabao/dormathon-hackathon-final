"""Post-activation measurement of the FAQ cache from the request ledger.

Avoided provider cost is an ESTIMATE: hits x average provider cost of comparable static_faq
provider calls. With owner-opted holdout (deterministic 10% of eligible requests sent to the
provider) the holdout group's average cost is used as the counterfactual instead. Mock-mode
traffic is flagged: its costs come from mock token estimates, not real provider usage.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiRequest, Policy
from app.services.history import app_maps

MIN_HOLDOUT = 30
CACHE_PROVIDER = "tokenguard-cache"


def measure(session: Session, workspace_id, cache_eval: dict | None) -> dict:
    s = get_settings()
    id_to_name, _ = app_maps(session, workspace_id)
    out = []
    for p in session.scalars(select(Policy).where(Policy.workspace_id == workspace_id,
                                                  Policy.policy_type == "semantic_cache")):  # fmt: skip
        app = id_to_name[p.application_id]
        if p.approved_at is None:
            out.append({"application": app, "status": "never_enabled", "policy_enabled": p.enabled})
            continue
        since = p.approved_at
        rows = session.execute(
            select(ApiRequest.cache_status, ApiRequest.cache_decision, ApiRequest.provider,
                   ApiRequest.request_category, ApiRequest.estimated_cost_myr)
            .where(ApiRequest.application_id == p.application_id, ApiRequest.occurred_at >= since,
                   ApiRequest.data_origin == "real")
        ).all()  # fmt: skip
        total = len(rows)
        hits = [r for r in rows if r.cache_status in ("exact_hit", "semantic_hit")]
        provider_calls = [r for r in rows if r.provider != CACHE_PROVIDER]
        faq_calls = [r for r in provider_calls if r.request_category == "static_faq" and r.cache_status != "error"]
        holdout = [r for r in provider_calls if (r.cache_decision or "").startswith("holdout_")]
        eligible = len(hits) + len(holdout)
        avg_faq_cost = (sum(float(r.estimated_cost_myr) for r in faq_calls) / len(faq_calls)) if faq_calls else None
        if avg_faq_cost is None:  # fall back to pre-activation static_faq calls
            avg_faq_cost = session.scalar(
                select(func.avg(ApiRequest.estimated_cost_myr)).where(
                    ApiRequest.application_id == p.application_id, ApiRequest.request_category == "static_faq",
                    ApiRequest.provider != CACHE_PROVIDER, ApiRequest.cache_status != "error",
                    ApiRequest.data_origin == "real",
                )
            )  # fmt: skip
            avg_faq_cost = float(avg_faq_cost) if avg_faq_cost is not None else None
        if len(holdout) >= MIN_HOLDOUT:
            unit = sum(float(r.estimated_cost_myr) for r in holdout) / len(holdout)
            method = f"holdout counterfactual ({len(holdout)} eligible requests deliberately sent to the provider)"
        else:
            unit = avg_faq_cost
            method = "observational estimate: hits x average cost of static_faq provider calls (not a controlled test)"
        days = max(1.0, (datetime.now(UTC) - since).total_seconds() / 86400)
        lookups = sum(r.request_category == "static_faq" for r in rows)
        overhead = lookups * s.cache_overhead_per_lookup_myr + s.cache_fixed_daily_myr * days
        avoided = len(hits) * unit if unit is not None else None
        mock = any(r.provider.endswith("-mock") for r in provider_calls)
        out.append({
            "application": app, "status": "enabled" if p.enabled else "disabled_after_enablement",
            "policy_enabled": p.enabled, "since": since.isoformat(), "days_observed": round(days, 2),
            "requests": total, "provider_calls": len(provider_calls),
            "exact_hits": sum(r.cache_status == "exact_hit" for r in hits),
            "semantic_hits": sum(r.cache_status == "semantic_hit" for r in hits),
            "bypassed": sum(r.cache_status == "bypass" for r in rows), "eligible_requests": eligible,
            "holdout_requests": len(holdout), "observed_provider_cost_myr": round(sum(float(r.estimated_cost_myr)
                                                                                      for r in provider_calls), 6),
            "estimated_avoided_provider_cost_myr": None if avoided is None else round(avoided, 6),
            "estimated_overhead_myr": round(overhead, 6),
            "estimated_net_savings_myr": None if avoided is None else round(avoided - overhead, 6),
            "method": method,
            "provider_mode": "mock" if mock else ("live" if provider_calls else "no_provider_calls"),
            "evidence": ("mock-mode accounting (no real provider spend)" if mock
                         else "observational, real traffic" if rows else "no traffic since enablement"),
        })  # fmt: skip
    return {
        "applications": out,
        "safe_hit_precision_on_test_set": None if cache_eval is None else cache_eval.get("hit_precision"),
        "adversarial_false_hits_on_test_set": None if cache_eval is None else cache_eval.get("adversarial_false_hits"),
        "note": "Savings are estimates. Use holdout (owner opt-in) for a controlled counterfactual.",
    }
