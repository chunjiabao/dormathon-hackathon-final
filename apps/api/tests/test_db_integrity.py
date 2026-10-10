import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import get_engine
from app.models import PolicyAudit
from app.services.seed import DEMO_OWNER_ID


def test_policy_audit_is_immutable(session, bakery_app):
    row = PolicyAudit(workspace_id=bakery_app.workspace_id, actor_user_id=DEMO_OWNER_ID, action="test")
    session.add(row)
    session.commit()
    with get_engine().connect() as conn:
        with pytest.raises(DBAPIError, match="immutable"):
            conn.execute(text("UPDATE policy_audit SET action = 'tampered' WHERE id = :id"), {"id": row.id})
        conn.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            conn.execute(text("DELETE FROM policy_audit WHERE id = :id"), {"id": row.id})


def test_negative_tokens_rejected(bakery_app):
    with get_engine().connect() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO api_requests (workspace_id, application_id, occurred_at, provider, model, "
                "request_category, input_tokens, cache_status, data_origin, request_fingerprint, "
                "pricing_version) "
                "VALUES (:w, :a, now(), 'x', 'm', 'other', -1, 'miss', 'real', 'fp', 'v')"
            ),
            {"w": bakery_app.workspace_id, "a": bakery_app.id},
        )


def test_policy_threshold_range_enforced(bakery_app):
    with get_engine().connect() as conn, pytest.raises(IntegrityError):
        conn.execute(
            text("UPDATE policies SET similarity_threshold = 0.5 WHERE application_id = :a"),
            {"a": bakery_app.id},
        )


def test_rls_enabled_on_all_tables():
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT relname FROM pg_class WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace "
                "AND relname <> 'alembic_version' AND NOT relrowsecurity"
            )
        ).all()
    assert rows == []


def test_demo_seed_is_idempotent(client):
    a = client.post("/api/v1/demo/seed").json()
    b = client.post("/api/v1/demo/seed").json()
    assert a == b
