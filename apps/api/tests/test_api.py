from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_dependencies_without_secrets():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["dependencies"]["anthropic"]["mode"] in {"mock", "live"}
    flat = res.text.lower()
    assert "api_key" not in flat and "secret" not in flat and "password" not in flat


def test_unknown_route_uses_error_envelope():
    res = client.get("/api/v1/does-not-exist", headers={"X-Request-ID": "abc-123"})
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "not_found"
    assert err["request_id"] == "abc-123"


def test_security_headers_present():
    res = client.get("/api/v1/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in res.headers


def test_health_is_unready_when_database_is_unavailable(monkeypatch):
    from app.api import health

    monkeypatch.setattr(health, "ping_database", lambda: "unavailable (OperationalError)")
    res = client.get("/api/v1/health")
    assert res.status_code == 503
    assert res.json()["status"] == "degraded"
