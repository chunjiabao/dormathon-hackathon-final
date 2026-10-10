"""Forecast / anomaly / usage / evaluation endpoints, auth and tenant isolation."""

from app.config import get_settings


def test_latest_forecast_contract(client, owner_headers, seeded):
    res = client.get("/api/v1/forecasts/latest", headers=owner_headers)
    assert res.status_code == 200
    f = res.json()
    assert f["status"] == "ok" and f["evidence_type"] == "synthetic"
    required = {
        "observed_to_date_myr", "predicted_remaining_myr", "forecast_total_myr", "lower_myr", "upper_myr",
        "budget_myr", "budget_risk", "series", "model_name", "training_cutoff", "data_mix", "assumptions",
    }  # fmt: skip
    assert required <= set(f)
    assert f["budget_risk"] in {
        "within_budget",
        "possible_overrun",
        "projected_overrun",
        "high_confidence_overrun",
    }
    kinds = {r["kind"] for r in f["series"]}
    assert kinds == {"actual", "forecast"}


def test_drivers_endpoint_and_isolation(client, owner_headers, other_owner_headers, seeded):
    url = f"/api/v1/forecasts/{seeded['run_id']}/drivers"
    d = client.get(url, headers=owner_headers).json()
    assert d["reconciles_with_forecast"] is True
    assert client.get(url, headers=other_owner_headers).status_code == 404


def test_forecast_run_owner_only(client, viewer_headers, owner_headers, seeded):
    assert client.post("/api/v1/forecasts/run", json={}, headers=viewer_headers).status_code == 403
    res = client.post("/api/v1/forecasts/run", json={"run_key": "api-test-run"}, headers=owner_headers)
    assert res.status_code == 200 and res.json()["status"] == "ok"
    again = client.post("/api/v1/forecasts/run", json={"run_key": "api-test-run"}, headers=owner_headers)
    assert again.json()["id"] == res.json()["id"]  # idempotent per run key


def test_anomalies_list_and_acknowledge(client, owner_headers, viewer_headers, seeded):
    items = client.get("/api/v1/anomalies", headers=viewer_headers).json()["items"]
    assert items
    first = items[0]
    assert first["is_synthetic"] and first["synthetic_ground_truth"] is not None
    assert "probability" in first["limitations"]
    url = f"/api/v1/anomalies/{first['id']}/acknowledge"
    assert client.post(url, headers=viewer_headers).status_code == 403
    ok = client.post(url, headers=owner_headers)
    assert ok.status_code == 200 and ok.json()["acknowledged_at"]
    high = client.get("/api/v1/anomalies?severity=high", headers=owner_headers).json()["items"]
    assert all(i["severity"] == "high" for i in high)


def test_other_workspace_sees_no_anomalies_or_usage(client, other_owner_headers, seeded):
    assert client.get("/api/v1/anomalies", headers=other_owner_headers).json()["items"] == []
    assert client.get("/api/v1/usage/daily", headers=other_owner_headers).json()["items"] == []


def test_usage_daily_labels_origin(client, owner_headers, seeded):
    res = client.get("/api/v1/usage/daily?from=2026-10-01&to=2026-10-09&data_origin=synthetic", headers=owner_headers)
    items = res.json()["items"]
    assert items and {i["data_origin"] for i in items} == {"synthetic"}
    assert all("2026-10-01" <= i["day"] <= "2026-10-09" for i in items)


def test_usage_requests_paginates_metadata_only(client, owner_headers, chat_headers, bakery_app):
    for msg in ("What time do you open?", "Do you deliver?", "Tell me a joke"):
        client.post("/api/v1/chat", json={"application_id": str(bakery_app.id), "message": msg}, headers=chat_headers)
    page1 = client.get("/api/v1/usage/requests?limit=2", headers=owner_headers).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"] and page1["total"] == 3
    page2 = client.get(f"/api/v1/usage/requests?limit=2&cursor={page1['next_cursor']}", headers=owner_headers).json()
    assert len(page2["items"]) == 1 and page2["next_cursor"] is None
    for item in page1["items"] + page2["items"]:
        assert "message" not in item and "prompt" not in item
        assert item["provider_mode"] == "mock"
    assert client.get("/api/v1/usage/requests?cursor=garbage", headers=owner_headers).status_code == 422


def test_evaluation_not_run_until_stored(client, owner_headers, seeded):
    res = client.get("/api/v1/evaluation/latest", headers=owner_headers).json()
    assert res["status"] == "not_run" and res["evaluation"] is None
    assert res["workspace_dataset"]["seed"] == 42


def test_scheduler_endpoint_requires_secret(client, monkeypatch):
    assert client.post("/api/v1/jobs/daily").status_code == 401
    monkeypatch.setattr(get_settings(), "scheduler_secret", "s3cret-value")
    assert client.post("/api/v1/jobs/daily", headers={"X-Scheduler-Secret": "wrong"}).status_code == 401


def test_usage_request_filters_keep_pagination_and_totals_scoped(
    client, owner_headers, other_owner_headers, chat_headers, bakery_app, session
):
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models import ApiRequest

    for msg in ("What time do you open?", "Do you deliver?", "Tell me a joke"):
        response = client.post(
            "/api/v1/chat", json={"application_id": str(bakery_app.id), "message": msg}, headers=chat_headers
        )
        assert response.status_code == 200
    rows = list(session.scalars(select(ApiRequest).order_by(ApiRequest.occurred_at)))
    # Kuala Lumpur midnight is 16:00 UTC the previous day. End date is inclusive.
    for row, stamp in zip(
        rows, ("2026-10-09T15:59:00+00:00", "2026-10-09T16:00:00+00:00", "2026-10-10T15:59:00+00:00"), strict=True
    ):
        row.occurred_at = datetime.fromisoformat(stamp).astimezone(UTC)
    session.commit()
    params = {"from": "2026-10-10", "to": "2026-10-10", "application": "bakery_demo", "data_origin": "real", "limit": 1}
    first = client.get("/api/v1/usage/requests", params=params, headers=owner_headers).json()
    assert first["total"] == 2 and len(first["items"]) == 1 and first["next_cursor"]
    second = client.get(
        "/api/v1/usage/requests", params={**params, "cursor": first["next_cursor"]}, headers=owner_headers
    ).json()
    assert second["total"] == 2 and len(second["items"]) == 1 and second["next_cursor"] is None
    assert first["items"][0]["id"] != second["items"][0]["id"]
    for filters in (
        {"application": "missing"},
        {"model": "missing"},
        {"request_category": "missing"},
        {"data_origin": "synthetic"},
    ):
        empty = client.get("/api/v1/usage/requests", params={**params, **filters}, headers=owner_headers).json()
        assert empty["items"] == [] and empty["total"] == 0
    other = client.get("/api/v1/usage/requests", params=params, headers=other_owner_headers).json()
    assert other["items"] == [] and other["total"] == 0


def test_usage_rejects_reversed_date_range(client, owner_headers):
    for endpoint in ("daily", "requests"):
        res = client.get(f"/api/v1/usage/{endpoint}?from=2026-10-11&to=2026-10-10", headers=owner_headers)
        assert res.status_code == 422
