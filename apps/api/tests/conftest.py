"""Test harness: real PostgreSQL + pgvector, mock Anthropic, never any cloud account.

Uses TEST_DATABASE_URL when set (CI service container); otherwise starts an embedded
PostgreSQL via `pgserver` in a temp directory.
"""

import os
import tempfile
import uuid
from datetime import date

import pytest

# Tests must never call real Anthropic or require cloud accounts.
os.environ["APP_ENV"] = "test"
os.environ["ANTHROPIC_MODE"] = "mock"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("SUPABASE_JWKS_URL", None)
os.environ["DEMO_MODE"] = "true"

TEST_DB = "tokenguard_test"
_server = None


def _database_url() -> str:
    global _server
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    import pgserver

    _server = pgserver.get_server(os.path.join(tempfile.gettempdir(), "tokenguard_pgtest"), cleanup_mode="stop")
    _server.psql(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE);")
    _server.psql(f"CREATE DATABASE {TEST_DB};")
    base = _server.get_uri().rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://", 1)
    return f"{base}/{TEST_DB}"


os.environ["DATABASE_URL"] = _database_url()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.auth import issue_dev_token  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.ratelimit import limiter  # noqa: E402
from app.services.anthropic_adapter import MockProvider, get_provider  # noqa: E402
from app.services.seed import (  # noqa: E402
    DEMO_OWNER_ID,
    DEMO_VIEWER_ID,
    bootstrap_demo,
    chat_application,
    ensure_workspace,
)

OTHER_OWNER_ID = uuid.UUID("00000000-0000-4000-8000-0000000000b1")
# Reset before every test. Analytical tables (daily_usage, forecasts, anomalies, evaluation_runs)
# are reset by the module-scoped `seeded` fixture so the expensive seed + forecast runs once.
MUTABLE_TABLES = "api_requests, response_cache"
ANALYTICAL_TABLES = (
    "recommendations, scenario_runs, forecast_points, forecast_runs, anomaly_events, daily_usage, evaluation_runs"
)
SYNTHETIC_END = date(2026, 10, 9)
TODAY = date(2026, 10, 10)


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    command.upgrade(cfg, "head")
    with Session(get_engine()) as s:
        bootstrap_demo(s)
        ensure_workspace(s, slug="other-ws", name="Other Workspace", owner_id=OTHER_OWNER_ID, viewer_id=None)
        s.commit()
    yield


@pytest.fixture(autouse=True)
def clean_state():
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {MUTABLE_TABLES}"))
        conn.execute(
            text(
                "UPDATE policies SET enabled = false, approved_by = NULL, approved_at = NULL, "
                "holdout_enabled = false, similarity_threshold = 0.95, ttl_hours = 24"
            )
        )
        conn.execute(text("UPDATE workspaces SET knowledge_version = 1"))
        conn.execute(text("UPDATE faq_entries SET expires_at = NULL, cacheable = true"))
        conn.execute(text("UPDATE applications SET app_key_hash = NULL"))
        conn.execute(text("UPDATE workspaces SET monthly_budget_myr = 200"))
    limiter.reset()
    yield


@pytest.fixture
def session():
    with Session(get_engine()) as s:
        yield s


@pytest.fixture
def mock_provider():
    provider = MockProvider("claude-haiku-4-5-20251001")
    app.dependency_overrides[get_provider] = lambda: provider
    yield provider
    app.dependency_overrides.pop(get_provider, None)


@pytest.fixture
def client(mock_provider):
    with TestClient(app) as c:
        yield c


def _auth(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {issue_dev_token(user_id)}"}


@pytest.fixture
def owner_headers():
    return _auth(DEMO_OWNER_ID)


@pytest.fixture
def viewer_headers():
    return _auth(DEMO_VIEWER_ID)


@pytest.fixture
def other_owner_headers():
    return _auth(OTHER_OWNER_ID)


@pytest.fixture
def bakery_app(session):
    return chat_application(session)


@pytest.fixture
def other_app(session):
    from app.models import Workspace

    ws = session.query(Workspace).filter_by(slug="other-ws").one()
    return chat_application(session, ws.id)


@pytest.fixture(scope="session")
def synthetic():
    """The deterministic seed-42 dataset with a fixed end date (generated once per test session)."""
    from app.ml.synthetic import generate

    return generate(42, 180, SYNTHETIC_END)


@pytest.fixture(scope="module")
def seeded(synthetic):
    """Demo workspace with synthetic history loaded, one forecast run and anomaly detection."""
    from app.models import Workspace
    from app.services.anomaly import detect_and_store
    from app.services.forecast import run_forecast
    from app.services.synthetic_loader import load_synthetic

    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {ANALYTICAL_TABLES}"))
    with Session(get_engine()) as s:
        ws = s.query(Workspace).filter_by(slug="sweet-crumbs").one()
        load_synthetic(s, ws, data_dir=None, generated=synthetic)
        run = run_forecast(s, ws, today=TODAY)
        anomalies = detect_and_store(s, ws, today=TODAY)
        yield {"workspace_id": ws.id, "run_id": run.id, "anomalies": anomalies}


@pytest.fixture
def chat_headers(client):
    token = client.post("/api/v1/chat/session").json()["token"]
    return {"Authorization": f"Bearer {token}"}
