"""Safe FAQ cache: gate, matching, policy behaviour, isolation, invalidation, holdout."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.ml.cache_eval import evaluate_cache, load_catalog
from app.models import ApiRequest, FaqEntry, Policy, ResponseCache, Workspace
from app.services import cache as faq_cache
from app.services import faq_eligibility
from app.services.anthropic_adapter import ProviderError
from app.services.seed import FAQ_FIXTURES, load_json


def _chat(client, headers, app_id, message):
    res = client.post("/api/v1/chat", json={"application_id": str(app_id), "message": message}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def _enable(session, app, **kw):
    session.execute(
        update(Policy).where(Policy.application_id == app.id).values(enabled=True, approved_at=datetime.now(UTC), **kw)
    )
    session.commit()


# ---------------------------------------------------------------- pure gate / matcher


@pytest.mark.parametrize("fixture", sorted(set(FAQ_FIXTURES.values())))
def test_every_approved_phrase_passes_gate_and_matches_itself(fixture):
    data = load_json(fixture)
    for e in data["entries"]:
        for phrase in [e["question"], *e["aliases"]]:
            gate = faq_eligibility.check(phrase, "en", data["products"])
            assert gate.eligible, (phrase, gate.reason)


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("Do you deliver to my address?", "pii"),
        ("Is my order ready?", "account_specific"),
        ("Can you refund order #1234?", "account_specific"),
        ("Do you have stock today?", "dynamic"),
        ("What are your hours tomorrow?", "dynamic"),
        ("Pukul berapa kedai buka?", "non_english"),
        ("¿A qué hora abren?", "non_english"),
        ("Are you not open on Sunday?", "negation"),
        ("What time do you open and do you deliver?", "multiple_questions"),
        ("How much is the Chocolate Vanilla cake?", "conflicting_products"),
        ("Any discount on cakes?", "discount"),
        ("Can I order a cake for 50 people?", "contains_number"),
    ],
)
def test_safety_gate_rejects_adversarial(query, reason):
    _, products = load_catalog()
    gate = faq_eligibility.check(query, "en", products)
    assert not gate.eligible and gate.reason == reason


def test_unsupported_locale_bypasses():
    assert faq_eligibility.check("When do you open?", "ms", []).reason == "locale_unsupported"


def test_key_term_guard_distinguishes_days_and_products():
    products = load_catalog()[1]
    assert faq_eligibility.key_terms("are you open on sundays", products) == {"sunday"}
    assert faq_eligibility.key_terms("how much is the midnight chocolate cake", products) == {"midnight chocolate"}


def test_labelled_set_has_zero_false_hits_and_reports_metrics():
    r = evaluate_cache()
    assert r["false_hits"] == 0 and r["adversarial_false_hits"] == 0
    assert r["hit_precision"] == 1.0
    assert r["by_group"]["positive_exact"]["correct_hits"] == r["by_group"]["positive_exact"]["n"]
    assert {s["threshold"] for s in r["threshold_sweep"]} >= {0.90, 0.95, 0.99}
    assert r["latency_ms"]["p95"] >= 0


def test_spec_adversarial_pairs_never_cross_answer():
    entries, products = load_catalog()
    pairs = [
        ("Do you open on Sunday?", "open_sunday"), ("Are you open Saturday?", "open_saturday"),
        ("How much is Chocolate Cake?", "price_midnight_chocolate"),
        ("How much is Vanilla Cake?", "price_vanilla_cloud"),
        ("Do you deliver?", "delivery_general"),
    ]  # fmt: skip
    for q, intent in pairs:
        assert faq_cache.match(entries, products, q, 0.95).intent_key == intent
    for q in ("Do you open on Monday?", "How much is the Strawberry Cake?", "Are you open on public holidays?"):
        d = faq_cache.match(entries, products, q, 0.95)
        assert not d.eligible, (q, d.decision, d.similarity)


# ---------------------------------------------------------------- gateway behaviour


def test_disabled_policy_never_serves_cache_but_records_shadow(client, chat_headers, bakery_app, mock_provider):
    body = _chat(client, chat_headers, bakery_app.id, "What time do you open?")
    assert body["cache_status"] == "miss" and body["cache_decision"] == "shadow_eligible_exact"
    assert body["faq_intent_key"] == "opening_hours"
    assert mock_provider.calls == 1


def test_safe_repeat_avoids_second_provider_call(client, chat_headers, bakery_app, mock_provider, session):
    _enable(session, bakery_app)
    first = _chat(client, chat_headers, bakery_app.id, "What time do you open?")
    second = _chat(client, chat_headers, bakery_app.id, "When are you open?")  # different phrasing, same intent
    third = _chat(client, chat_headers, bakery_app.id, "What time do you open?")  # new DB session (regression)
    assert {first["cache_status"], second["cache_status"], third["cache_status"]} == {"exact_hit"}
    assert mock_provider.calls == 0
    assert first["reply"] == second["reply"] and "Monday to Saturday" in first["reply"]
    assert first["provider_mode"] == "none" and first["usage"] == {"input_tokens": 0, "output_tokens": 0}
    assert first["estimated_cost_myr"] == 0
    row = session.scalars(select(ResponseCache).where(ResponseCache.application_id == bakery_app.id)).first()
    assert row.hit_count >= 1 and row.expires_at > datetime.now(UTC)


def test_semantic_hit_without_provider_call(client, chat_headers, bakery_app, mock_provider, session):
    _enable(session, bakery_app)
    body = _chat(client, chat_headers, bakery_app.id, "Are you open on Sundays?")
    assert body["cache_status"] == "semantic_hit" and body["faq_intent_key"] == "open_sunday"
    assert body["similarity"] >= 0.95
    assert mock_provider.calls == 0


@pytest.mark.parametrize(
    ("message", "status"),
    [
        ("Do you open on Monday?", "miss"),  # near-match, different answer
        ("Do you deliver to my address?", "bypass"),  # personalised
        ("Is my order ready?", "bypass"),
        ("Tell me a joke", "miss"),
    ],
)
def test_unsafe_or_unmatched_requests_call_provider(client, chat_headers, bakery_app, mock_provider, session, message,
                                                    status):  # fmt: skip
    _enable(session, bakery_app)
    body = _chat(client, chat_headers, bakery_app.id, message)
    assert body["cache_status"] == status
    assert mock_provider.calls == 1


def test_expired_faq_entry_is_not_served(client, chat_headers, bakery_app, mock_provider, session):
    _enable(session, bakery_app)
    session.execute(update(FaqEntry).where(FaqEntry.application_id == bakery_app.id,
                                           FaqEntry.intent_key == "opening_hours")
                    .values(expires_at=datetime.now(UTC) - timedelta(hours=1)))  # fmt: skip
    session.commit()
    assert _chat(client, chat_headers, bakery_app.id, "What time do you open?")["cache_status"] == "miss"
    assert mock_provider.calls == 1


def test_cross_tenant_answers_never_reused(client, chat_headers, bakery_app, other_app, mock_provider, session):
    session.execute(update(FaqEntry).where(FaqEntry.application_id == other_app.id)
                    .values(approved_answer="OTHER WORKSPACE ANSWER"))  # fmt: skip
    session.commit()
    _enable(session, bakery_app)
    body = _chat(client, chat_headers, bakery_app.id, "What time do you open?")
    assert body["cache_status"] == "exact_hit" and "OTHER WORKSPACE" not in body["reply"]
    ws = session.get(Workspace, bakery_app.workspace_id)
    entries = faq_cache.active_entries(session, bakery_app, ws, "en", datetime.now(UTC))
    assert entries and all(e.workspace_id == ws.id and e.application_id == bakery_app.id for e in entries)


def test_faq_version_bump_invalidates_cache(client, chat_headers, owner_headers, bakery_app, mock_provider, session):
    _enable(session, bakery_app)
    assert _chat(client, chat_headers, bakery_app.id, "Do you deliver?")["cache_status"] == "exact_hit"
    assert client.post("/api/v1/faq/invalidate", headers=owner_headers).json()["knowledge_version"] == 2
    count = session.scalar(select(func.count()).select_from(ResponseCache)
                           .where(ResponseCache.workspace_id == bakery_app.workspace_id))  # fmt: skip
    assert count == 0
    body = _chat(client, chat_headers, bakery_app.id, "Do you deliver?")
    assert body["cache_status"] == "miss" and body["cache_decision"] == "no_approved_faq"
    assert mock_provider.calls == 1


def test_provider_failure_is_never_cached(client, chat_headers, bakery_app, mock_provider, session):
    _enable(session, bakery_app)
    mock_provider.fail_next = ProviderError("provider_timeout", transient=True)
    res = client.post("/api/v1/chat", json={"application_id": str(bakery_app.id), "message": "Tell me a joke"},
                      headers=chat_headers)  # fmt: skip
    assert res.status_code == 502
    assert session.scalar(select(func.count()).select_from(ResponseCache)) == 0
    assert session.scalars(select(ApiRequest.cache_status)).all() == ["error"]


def test_holdout_sends_deterministic_share_to_provider(
    client, chat_headers, bakery_app, mock_provider, session, monkeypatch
):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_ip_per_min", 1000)  # this test sends >30 requests
    _enable(session, bakery_app, holdout_enabled=True)
    phrases = [p for e in load_json("bakery_faq.json")["entries"] for p in [e["question"], *e["aliases"]]]
    results = [_chat(client, chat_headers, bakery_app.id, p) for p in phrases]
    held = [r for r in results if (r["cache_decision"] or "").startswith("holdout_")]
    assert held and all(r["cache_status"] == "miss" for r in held)
    assert mock_provider.calls == len(held) < len(results)
    again = [_chat(client, chat_headers, bakery_app.id, r) for r in phrases[:5]]
    assert [a["cache_decision"] for a in again] == [r["cache_decision"] for r in results[:5]]  # deterministic


def test_mock_provider_ids_unique_across_instances():
    from app.services.anthropic_adapter import MockProvider

    a = MockProvider("m").complete("s", "hello", 10).provider_request_id
    b = MockProvider("m").complete("s", "hello", 10).provider_request_id
    assert a != b


def test_health_reports_embedding_status_without_loading(client):
    emb = client.get("/api/v1/health").json()["dependencies"]["embeddings"]
    assert emb["semantic_matching"] in {"available", "loading", "unavailable", "disabled"}


def test_eval_set_fixture_is_well_formed():
    data = json.loads(open("app/fixtures/cache_eval_set.json", encoding="utf-8").read())
    groups = {i["group"] for i in data["items"]}
    assert groups == {"positive_exact", "positive_paraphrase", "adversarial"}
    assert sum(i["group"] == "adversarial" for i in data["items"]) >= 20
