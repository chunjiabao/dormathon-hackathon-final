import pytest
from sqlalchemy import select

from app.models import ApiRequest
from app.services.anthropic_adapter import ProviderError
from app.services.costing import TokenUsage, cost_myr, get_rates
from app.services.usage_logger import fingerprint


def _chat(client, headers, app_id, message="Can you recommend a cake for a birthday party?"):
    return client.post("/api/v1/chat", json={"application_id": str(app_id), "message": message}, headers=headers)


def test_miss_calls_provider_once_and_records_usage(client, chat_headers, bakery_app, mock_provider, session):
    msg = "Can you recommend a cake for a birthday party?"
    res = _chat(client, chat_headers, bakery_app.id, msg)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cache_status"] == "miss"
    assert body["provider_mode"] == "mock"
    assert mock_provider.calls == 1

    row = session.scalar(select(ApiRequest).where(ApiRequest.id == body["request_id"]))
    assert row.provider == "anthropic-mock"
    assert row.data_origin == "real"
    assert row.input_tokens == body["usage"]["input_tokens"] > 0
    assert row.output_tokens == body["usage"]["output_tokens"] > 0
    rates = get_rates(session, "claude-haiku-4-5-20251001", "demo-2025-10")
    expected = cost_myr(TokenUsage(row.input_tokens, row.output_tokens), rates, 4.70)
    assert row.estimated_cost_myr == expected
    assert body["estimated_cost_myr"] == pytest.approx(float(expected), abs=1e-9)
    assert row.request_fingerprint == fingerprint(bakery_app.workspace_id, msg)


def test_raw_message_is_never_persisted(client, chat_headers, bakery_app, session):
    secret_msg = "My phone is 0123456789 can you call me about a birthday cake"
    assert _chat(client, chat_headers, bakery_app.id, secret_msg).status_code == 200
    row = session.scalars(select(ApiRequest)).one()
    for col in ApiRequest.__table__.columns:
        value = getattr(row, col.key)
        if isinstance(value, str):
            assert "0123456789" not in value and "birthday" not in value


def test_fingerprint_is_keyed_and_normalized(bakery_app):
    a = fingerprint(bakery_app.workspace_id, "  What TIME do you open? ")
    b = fingerprint(bakery_app.workspace_id, "what time do you open?")
    import hashlib

    assert a == b
    assert a != hashlib.sha256(b"what time do you open?").hexdigest()


def test_provider_failure_is_logged_not_cached(client, chat_headers, bakery_app, mock_provider, session):
    mock_provider.fail_next = ProviderError("provider_timeout", transient=True)
    res = _chat(client, chat_headers, bakery_app.id)
    assert res.status_code == 502
    err = res.json()["error"]
    assert err["code"] == "provider_unavailable"
    assert "timeout" not in err["message"].lower()  # no internal detail leaks
    row = session.scalars(select(ApiRequest)).one()
    assert row.cache_status == "error" and row.error_code == "provider_timeout"
    assert row.input_tokens == 0 and row.estimated_cost_myr == 0
    # Next identical request goes to the provider again (nothing cached from the failure).
    assert _chat(client, chat_headers, bakery_app.id).json()["cache_status"] == "miss"
    assert mock_provider.calls == 2


def test_input_validation(client, chat_headers, bakery_app, mock_provider):
    assert _chat(client, chat_headers, bakery_app.id, "x" * 1001).status_code == 422
    assert _chat(client, chat_headers, bakery_app.id, "   ").status_code == 422
    res = client.post(
        "/api/v1/chat",
        json={"application_id": str(bakery_app.id), "message": "hi", "locale": "english!!"},
        headers=chat_headers,
    )
    assert res.status_code == 422
    assert mock_provider.calls == 0


def test_chat_requires_credentials(client, bakery_app):
    assert _chat(client, {}, bakery_app.id).status_code == 401
    assert _chat(client, {"Authorization": "Bearer nope"}, bakery_app.id).status_code == 401


def test_member_user_token_can_chat(client, owner_headers, bakery_app):
    assert _chat(client, owner_headers, bakery_app.id).status_code == 200


def test_app_key_rotation_and_use(client, owner_headers, viewer_headers, bakery_app):
    url = f"/api/v1/applications/{bakery_app.id}/rotate-key"
    assert client.post(url, headers=viewer_headers).status_code == 403
    res = client.post(url, headers=owner_headers)
    assert res.status_code == 200
    key = res.json()["api_key"]
    assert _chat(client, {"X-App-Key": key}, bakery_app.id).status_code == 200
    assert _chat(client, {"X-App-Key": "tg_wrong"}, bakery_app.id).status_code == 401
    # Rotation invalidates the previous key.
    client.post(url, headers=owner_headers)
    assert _chat(client, {"X-App-Key": key}, bakery_app.id).status_code == 401


def test_rate_limit(client, chat_headers, bakery_app, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_ip_per_min", 2)
    assert _chat(client, chat_headers, bakery_app.id).status_code == 200
    assert _chat(client, chat_headers, bakery_app.id).status_code == 200
    res = _chat(client, chat_headers, bakery_app.id)
    assert res.status_code == 429
    assert res.json()["error"]["code"] == "rate_limited"


def test_request_categories_are_deterministic(client, chat_headers, bakery_app):
    cases = {
        "What time do you open?": "static_faq",
        "Is my order ready?": "order_enquiry",
        "My cake arrived damaged": "complex_support",
        "Tell me a joke": "other",
    }
    for msg, expected in cases.items():
        assert _chat(client, chat_headers, bakery_app.id, msg).json()["request_category"] == expected
