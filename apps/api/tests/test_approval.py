"""Owner-only approval workflow, policy activation, emergency disable, audit, measurement."""

import pytest
from sqlalchemy import func, select

from app.models import ForecastRun, PolicyAudit, Workspace
from app.services import recommender as rec_service

from .conftest import TODAY

GOOD_EVAL = {"false_hits": 0, "n": 51, "hit_precision": 1.0, "adversarial_false_hits": 0}


@pytest.fixture
def proposal(client, owner_headers, seeded, monkeypatch):
    monkeypatch.setattr(rec_service, "cache_evaluation", lambda s: GOOD_EVAL)
    res = client.post("/api/v1/recommendations/generate", headers=owner_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action_type"] == "enable_semantic_cache"
    return body


def _audit_count(session, action):
    return session.scalar(select(func.count()).select_from(PolicyAudit).where(PolicyAudit.action == action))


def _approve(client, headers, rec, version=None, holdout=False):
    return client.post(f"/api/v1/recommendations/{rec['id']}/approve",
                       json={"expected_version": rec["version"] if version is None else version,
                             "enable_holdout": holdout}, headers=headers)  # fmt: skip


def test_viewer_cannot_decide(client, viewer_headers, proposal):
    assert _approve(client, viewer_headers, proposal).status_code == 403
    url = f"/api/v1/recommendations/{proposal['id']}/reject"
    assert client.post(url, json={"expected_version": 1}, headers=viewer_headers).status_code == 403
    assert client.post("/api/v1/recommendations/generate", headers=viewer_headers).status_code == 403
    pol = client.get("/api/v1/policies", headers=viewer_headers).json()["items"][0]
    assert client.post(f"/api/v1/policies/{pol['id']}/disable", headers=viewer_headers).status_code == 403
    assert (
        client.patch(f"/api/v1/policies/{pol['id']}", json={"ttl_hours": 5}, headers=viewer_headers).status_code == 403
    )


def test_other_workspace_owner_cannot_decide(client, other_owner_headers, proposal):
    assert _approve(client, other_owner_headers, proposal).status_code == 404


def test_approval_enables_policies_changes_cache_and_is_idempotent(
    client, owner_headers, chat_headers, bakery_app, mock_provider, proposal, session
):
    msg = {"application_id": str(bakery_app.id), "message": "Do you deliver?"}
    assert client.post("/api/v1/chat", json=msg, headers=chat_headers).json()["cache_status"] == "miss"
    assert mock_provider.calls == 1

    assert _approve(client, owner_headers, proposal, version=proposal["version"] + 5).status_code == 409
    res = _approve(client, owner_headers, proposal)
    assert res.status_code == 200 and res.json()["status"] == "enabled"
    policies = client.get("/api/v1/policies", headers=owner_headers).json()["items"]
    assert policies and all(p["enabled"] and p["approved_by"] for p in policies)
    enabled_audits = _audit_count(session, "policy_enabled")
    assert enabled_audits == len(policies) and _audit_count(session, "recommendation_approved") == 1

    again = _approve(client, owner_headers, proposal)  # idempotent: no duplicate changes or audit
    assert again.status_code == 200 and _audit_count(session, "policy_enabled") == enabled_audits

    hit = client.post("/api/v1/chat", json=msg, headers=chat_headers).json()
    assert hit["cache_status"] == "exact_hit" and mock_provider.calls == 1  # approved policy changed behaviour

    bakery_policy = next(p for p in policies if p["application"] == "bakery_demo")
    off = client.post(f"/api/v1/policies/{bakery_policy['id']}/disable", headers=owner_headers)
    assert off.status_code == 200 and off.json()["enabled"] is False
    assert _audit_count(session, "policy_disabled") == 1
    after = client.post("/api/v1/chat", json=msg, headers=chat_headers).json()
    assert after["cache_status"] == "miss" and mock_provider.calls == 2  # disable restores provider calls
    recs = client.get("/api/v1/recommendations", headers=owner_headers).json()["items"]
    assert next(r for r in recs if r["id"] == proposal["id"])["status"] == "disabled"


def test_reject_flow(client, owner_headers, proposal, session):
    url = f"/api/v1/recommendations/{proposal['id']}/reject"
    res = client.post(url, json={"expected_version": proposal["version"]}, headers=owner_headers)
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    assert _approve(client, owner_headers, res.json()).status_code == 409
    assert _audit_count(session, "recommendation_rejected") == 1


def test_stale_recommendation_cannot_be_approved(client, owner_headers, proposal, session):
    from app.services.forecast import run_forecast

    ws = session.get(Workspace, session.get(ForecastRun, proposal["forecast_run_id"]).workspace_id)
    run_forecast(session, ws, today=TODAY)  # newer forecast supersedes the proposal
    res = _approve(client, owner_headers, proposal)
    assert res.status_code == 409 and res.json()["error"]["code"] == "stale"


def test_no_action_recommendation_has_nothing_to_approve(client, owner_headers, seeded, monkeypatch):
    monkeypatch.setattr(rec_service, "cache_evaluation", lambda s: {**GOOD_EVAL, "false_hits": 3})
    rec = client.post("/api/v1/recommendations/generate", headers=owner_headers).json()
    assert rec["action_type"] == "no_action"
    assert _approve(client, owner_headers, rec).status_code == 400


def test_policy_patch_bounds_and_audit(client, owner_headers, seeded, session):
    pol = client.get("/api/v1/policies", headers=owner_headers).json()["items"][0]
    url = f"/api/v1/policies/{pol['id']}"
    assert client.patch(url, json={"similarity_threshold": 0.9}, headers=owner_headers).status_code == 422
    assert client.patch(url, json={"ttl_hours": 0}, headers=owner_headers).status_code == 422
    ok = client.patch(url, json={"similarity_threshold": 0.97, "holdout_enabled": True}, headers=owner_headers)
    assert ok.status_code == 200 and ok.json()["similarity_threshold"] == 0.97 and ok.json()["holdout_enabled"]
    assert _audit_count(session, "policy_updated") == 1
    audit = client.get("/api/v1/audit", headers=owner_headers).json()["items"]
    assert audit[0]["action"] == "policy_updated" and audit[0]["old_value"]["similarity_threshold"] == 0.95


def test_measurement_after_enablement(client, owner_headers, chat_headers, bakery_app, proposal):
    assert _approve(client, owner_headers, proposal).status_code == 200
    for m in ("What time do you open?", "When do you open?", "Is my order ready?"):
        client.post("/api/v1/chat", json={"application_id": str(bakery_app.id), "message": m}, headers=chat_headers)
    res = client.get("/api/v1/measurement", headers=owner_headers).json()
    bakery = next(a for a in res["applications"] if a["application"] == "bakery_demo")
    assert bakery["exact_hits"] == 2 and bakery["provider_calls"] == 1 and bakery["bypassed"] == 1
    assert bakery["provider_mode"] == "mock" and "mock" in bakery["evidence"]
    assert "observational" in bakery["method"]
    assert res["safe_hit_precision_on_test_set"] == 1.0


def test_overview_endpoint_combines_state(client, owner_headers, seeded):
    o = client.get("/api/v1/overview", headers=owner_headers).json()
    assert o["workspace"]["budget_myr"] == 200.0
    assert o["forecast"]["status"] == "ok" and o["top_drivers"]
    assert o["live_traffic_7d"]["data_origin"] == "real"
    assert {p["application"] for p in o["policies"]} == {"bakery_demo", "tuition_demo", "retail_demo"}
