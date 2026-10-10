import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import CurrentUser, DbSession, require_member
from app.errors import ApiError
from app.models import ForecastRun, Policy, PolicyAudit, Recommendation, ScenarioRun, Workspace
from app.services import cache as faq_cache
from app.services.evaluation import cache_evaluation
from app.services.history import app_maps
from app.services.measurement import measure
from app.services.recommender import (
    ApprovalError,
    approve,
    disable_policy,
    latest_forecast_id,
    policy_state,
    recommend,
    reject,
)
from app.services.simulator import run_scenario

router = APIRouter(tags=["decisions"])


class ScenarioAssumptions(BaseModel):
    eligible_share: float | None = Field(default=None, ge=0, le=1)
    safe_hit_rate: float | None = Field(default=None, ge=0, le=1)
    overhead_per_lookup_myr: float | None = Field(default=None, ge=0, le=0.01)
    fixed_daily_myr: float | None = Field(default=None, ge=0, le=50)
    target_apps: list[str] | None = None


class CompareRequest(BaseModel):
    """No cost figures are accepted from the client: the baseline is always the persisted forecast."""

    workspace_id: uuid.UUID | None = None
    forecast_run_id: uuid.UUID | None = None
    actions: list[Literal["none", "semantic_cache"]] = ["none", "semantic_cache"]
    assumptions: ScenarioAssumptions = ScenarioAssumptions()


class DecisionBody(BaseModel):
    expected_version: int
    enable_holdout: bool = False


class PolicyPatch(BaseModel):
    similarity_threshold: float | None = Field(default=None, ge=0.95, le=0.99)
    ttl_hours: int | None = Field(default=None, ge=1, le=168)
    holdout_enabled: bool | None = None


def _raise(e: ApprovalError):
    raise ApiError(e.status, e.code, e.message) from e


@router.post("/scenarios/compare")
def compare(body: CompareRequest, principal: CurrentUser, session: DbSession) -> dict:
    m = require_member(session, principal, body.workspace_id)
    run_id = body.forecast_run_id or latest_forecast_id(session, m.workspace_id)
    run = session.get(ForecastRun, run_id) if run_id else None
    if run is None or run.workspace_id != m.workspace_id:
        raise ApiError(404, "not_found", "Forecast not found.")
    if run.status != "ok":
        raise ApiError(409, "forecast_unavailable", "This forecast has insufficient data for scenarios.")
    cache_eval = cache_evaluation(session)
    results = [
        run_scenario(session, run, a, body.assumptions.model_dump(exclude_none=True), cache_eval)[1]
        for a in body.actions
    ]
    session.commit()
    return {"forecast_run_id": str(run.id), "scenarios": results}


def _serialize_rec(session, rec: Recommendation, latest_id) -> dict:
    sr = session.get(ScenarioRun, rec.scenario_run_id) if rec.scenario_run_id else None
    return {
        "id": str(rec.id), "action_type": rec.action_type, "status": rec.status, "version": rec.version,
        "rationale": rec.rationale, "created_at": rec.created_at.isoformat(),
        "decided_at": rec.decided_at.isoformat() if rec.decided_at else None,
        "decided_by": str(rec.decided_by) if rec.decided_by else None,
        "forecast_run_id": str(rec.forecast_run_id), "superseded": rec.forecast_run_id != latest_id,
        "scenario": (sr.uncertainty_json or {}).get("result") if sr else None,
    }  # fmt: skip


@router.post("/recommendations/generate")
def generate(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    m = require_member(session, principal, workspace_id, role="owner")
    run_id = latest_forecast_id(session, m.workspace_id)
    if run_id is None:
        raise ApiError(409, "forecast_unavailable", "Run a forecast first.")
    try:
        rec = recommend(session, session.get(ForecastRun, run_id))
    except ApprovalError as e:
        _raise(e)
    return _serialize_rec(session, rec, run_id)


@router.get("/recommendations")
def list_recommendations(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    m = require_member(session, principal, workspace_id)
    latest = latest_forecast_id(session, m.workspace_id)
    recs = session.scalars(
        select(Recommendation)
        .where(Recommendation.workspace_id == m.workspace_id)
        .order_by(Recommendation.created_at.desc())
        .limit(20)
    )
    return {"items": [_serialize_rec(session, r, latest) for r in recs], "next_cursor": None}


def _owned_rec(session, principal, rec_id) -> Recommendation:
    rec = session.get(Recommendation, rec_id)
    if rec is None:
        raise ApiError(404, "not_found", "Recommendation not found.")
    require_member(session, principal, rec.workspace_id, role="owner")
    return rec


@router.post("/recommendations/{rec_id}/approve")
def approve_rec(rec_id: uuid.UUID, body: DecisionBody, principal: CurrentUser, session: DbSession) -> dict:
    rec = _owned_rec(session, principal, rec_id)
    try:
        rec = approve(session, rec, principal.user_id, body.expected_version, body.enable_holdout)
    except ApprovalError as e:
        _raise(e)
    return _serialize_rec(session, rec, latest_forecast_id(session, rec.workspace_id))


@router.post("/recommendations/{rec_id}/reject")
def reject_rec(rec_id: uuid.UUID, body: DecisionBody, principal: CurrentUser, session: DbSession) -> dict:
    rec = _owned_rec(session, principal, rec_id)
    try:
        rec = reject(session, rec, principal.user_id, body.expected_version)
    except ApprovalError as e:
        _raise(e)
    return _serialize_rec(session, rec, latest_forecast_id(session, rec.workspace_id))


def _policy_out(p: Policy, names: dict) -> dict:
    return {"id": str(p.id), "application": names.get(p.application_id), "policy_type": p.policy_type,
            **policy_state(p), "approved_at": p.approved_at.isoformat() if p.approved_at else None,
            "approved_by": str(p.approved_by) if p.approved_by else None,
            "updated_at": p.updated_at.isoformat()}  # fmt: skip


@router.get("/policies")
def list_policies(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    m = require_member(session, principal, workspace_id)
    names, _ = app_maps(session, m.workspace_id)
    ps = session.scalars(select(Policy).where(Policy.workspace_id == m.workspace_id))
    return {"items": [_policy_out(p, names) for p in ps], "next_cursor": None}


def _owned_policy(session, principal, policy_id) -> Policy:
    p = session.get(Policy, policy_id)
    if p is None:
        raise ApiError(404, "not_found", "Policy not found.")
    require_member(session, principal, p.workspace_id, role="owner")
    return p


@router.post("/policies/{policy_id}/disable")
def disable(policy_id: uuid.UUID, principal: CurrentUser, session: DbSession) -> dict:
    p = disable_policy(session, _owned_policy(session, principal, policy_id), principal.user_id)
    names, _ = app_maps(session, p.workspace_id)
    return _policy_out(p, names)


@router.patch("/policies/{policy_id}")
def patch_policy(policy_id: uuid.UUID, body: PolicyPatch, principal: CurrentUser, session: DbSession) -> dict:
    from datetime import UTC, datetime

    from sqlalchemy import delete

    from app.models import ResponseCache

    p = _owned_policy(session, principal, policy_id)
    old = policy_state(p)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(p, k, v)
    if changes:
        p.version += 1
        p.updated_at = datetime.now(UTC)
        if "similarity_threshold" in changes or "ttl_hours" in changes:
            session.execute(delete(ResponseCache).where(ResponseCache.application_id == p.application_id))
        session.add(PolicyAudit(workspace_id=p.workspace_id, application_id=p.application_id,
                                actor_user_id=principal.user_id, action="policy_updated", old_value=old,
                                new_value=policy_state(p)))  # fmt: skip
        session.commit()
    names, _ = app_maps(session, p.workspace_id)
    return _policy_out(p, names)


@router.get("/audit")
def audit_log(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    m = require_member(session, principal, workspace_id)
    names, _ = app_maps(session, m.workspace_id)
    rows = session.scalars(
        select(PolicyAudit).where(PolicyAudit.workspace_id == m.workspace_id).order_by(PolicyAudit.created_at.desc())
        .limit(100)
    )  # fmt: skip
    return {"items": [{"id": str(a.id), "created_at": a.created_at.isoformat(), "action": a.action,
                       "application": names.get(a.application_id), "actor_user_id": str(a.actor_user_id),
                       "old_value": a.old_value, "new_value": a.new_value} for a in rows],
            "next_cursor": None}  # fmt: skip


@router.get("/measurement")
def measurement(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    m = require_member(session, principal, workspace_id)
    return measure(session, m.workspace_id, cache_evaluation(session))


@router.post("/faq/invalidate")
def invalidate_faq(principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None) -> dict:
    """Owner: bump the knowledge version; every cached answer stops matching immediately."""
    m = require_member(session, principal, workspace_id, role="owner")
    ws = session.get(Workspace, m.workspace_id)
    old = ws.knowledge_version
    new = faq_cache.bump_knowledge_version(session, ws)
    session.add(PolicyAudit(workspace_id=ws.id, actor_user_id=principal.user_id, action="faq_version_bumped",
                            old_value={"knowledge_version": old}, new_value={"knowledge_version": new}))  # fmt: skip
    session.commit()
    return {"knowledge_version": new}
