from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.auth import DEV_ISSUER
from app.config import get_settings
from app.models import PolicyAudit
from app.services.seed import DEMO_OWNER_ID


def _token(secret: str | None = None, **overrides):
    now = datetime.now(UTC)
    claims = {
        "sub": str(DEMO_OWNER_ID),
        "aud": "authenticated",
        "iss": DEV_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **overrides,
    }
    key = secret or get_settings().dev_jwt_secret
    return {"Authorization": f"Bearer {jwt.encode(claims, key, algorithm='HS256')}"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer garbage"},
        "expired",
        "wrong_aud",
        "wrong_iss",
        "wrong_secret",
    ],
)
def test_invalid_tokens_rejected(client, headers):
    if headers == "expired":
        headers = _token(exp=datetime.now(UTC) - timedelta(minutes=1))
    elif headers == "wrong_aud":
        headers = _token(aud="someone-else")
    elif headers == "wrong_iss":
        headers = _token(iss="evil")
    elif headers == "wrong_secret":
        headers = _token(secret="not-the-secret-not-the-secret-123")
    res = client.get("/api/v1/me", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_chat_token_cannot_access_owner_endpoints(client, chat_headers):
    assert client.get("/api/v1/me", headers=chat_headers).status_code == 401
    assert client.get("/api/v1/settings/workspace", headers=chat_headers).status_code == 401


def test_me_lists_memberships(client, owner_headers, viewer_headers):
    owner = client.get("/api/v1/me", headers=owner_headers).json()
    assert [m["role"] for m in owner["memberships"]] == ["owner"]
    viewer = client.get("/api/v1/me", headers=viewer_headers).json()
    assert [m["role"] for m in viewer["memberships"]] == ["viewer"]


def test_dev_login_issues_working_tokens(client):
    for role in ("owner", "viewer"):
        token = client.post("/api/v1/auth/dev-login", json={"role": role}).json()["access_token"]
        me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert me["memberships"][0]["role"] == role


def test_dev_endpoints_hidden_outside_demo(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", False)
    assert client.post("/api/v1/auth/dev-login", json={"role": "owner"}).status_code == 404
    assert client.post("/api/v1/demo/seed").status_code == 404


def test_dev_tokens_rejected_when_jwks_configured(client, owner_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "supabase_jwks_url", "https://example.invalid/jwks.json")
    assert client.get("/api/v1/me", headers=owner_headers).status_code == 401


def test_settings_read_by_viewer_but_only_owner_can_patch(client, owner_headers, viewer_headers, session):
    res = client.get("/api/v1/settings/workspace", headers=viewer_headers)
    assert res.status_code == 200
    assert res.json()["monthly_budget_myr"] == 200.0
    assert res.json()["role"] == "viewer"

    denied = client.patch("/api/v1/settings/workspace", json={"monthly_budget_myr": 300}, headers=viewer_headers)
    assert denied.status_code == 403

    ok = client.patch("/api/v1/settings/workspace", json={"monthly_budget_myr": 300}, headers=owner_headers)
    assert ok.status_code == 200 and ok.json()["monthly_budget_myr"] == 300.0
    audit = session.scalars(select(PolicyAudit).where(PolicyAudit.action == "settings_update")).all()
    assert audit[-1].old_value["monthly_budget_myr"] == 200.0
    assert audit[-1].new_value["monthly_budget_myr"] == 300.0


def test_settings_patch_validation(client, owner_headers):
    assert (
        client.patch("/api/v1/settings/workspace", json={"monthly_budget_myr": -1}, headers=owner_headers).status_code
        == 422
    )
    assert (
        client.patch("/api/v1/settings/workspace", json={"timezone": "Mars/Base"}, headers=owner_headers).status_code
        == 422
    )


def test_production_config_guards():
    from app.config import Settings, validate_settings

    base = dict(
        app_env="production",
        demo_mode=False,
        supabase_url="https://x.supabase.co",
        supabase_jwks_url="https://x.supabase.co/auth/v1/.well-known/jwks.json",
        database_url="postgresql+psycopg://example:example@db.example/test?sslmode=require",
        scheduler_secret="c" * 32,
        chat_token_secret="a" * 32,
        fingerprint_secret="b" * 32,
        allowed_origins=["https://app.example"],
    )
    validate_settings(Settings(**base))
    for bad in (
        {"allowed_origins": ["*"]},
        {"demo_mode": True},
        {"supabase_jwks_url": None},
        {"chat_token_secret": None},
        {"fingerprint_secret": None},
        {"supabase_url": None},
        {"supabase_jwks_url": "https://other.supabase.co/auth/v1/.well-known/jwks.json"},
        {"allowed_origins": ["http://app.example"]},
        {"chat_token_secret": "short"},
        {"scheduler_secret": "change-me"},
        {"database_url": "postgresql+psycopg://example:example@db.example/test"},
    ):
        with pytest.raises(RuntimeError):
            validate_settings(Settings(**{**base, **bad}))
