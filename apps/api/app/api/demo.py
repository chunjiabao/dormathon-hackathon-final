"""Local/dev-only endpoints. Every route here is refused in production or when DEMO_MODE is off."""

from fastapi import APIRouter
from sqlalchemy import delete, update

from app.auth import CurrentUser, DbSession, issue_dev_token, require_member
from app.config import get_settings
from app.errors import ApiError
from app.models import (
    AnomalyEvent,
    ApiRequest,
    DailyUsage,
    ForecastRun,
    Policy,
    PolicyAudit,
    Recommendation,
    ResponseCache,
    ScenarioRun,
)
from app.schemas import DevLoginRequest, TokenResponse
from app.services.seed import DEMO_OWNER_ID, DEMO_VIEWER_ID, bootstrap_demo

router = APIRouter(tags=["demo"])


def _require_demo() -> None:
    s = get_settings()
    if s.is_production or not s.demo_mode:
        raise ApiError(404, "not_found", "Not found.")


@router.post("/auth/dev-login", response_model=TokenResponse)
def dev_login(body: DevLoginRequest) -> TokenResponse:
    """Issue a local dev token for the fixed demo owner or viewer identity."""
    _require_demo()
    user_id = DEMO_OWNER_ID if body.role == "owner" else DEMO_VIEWER_ID
    return TokenResponse(access_token=issue_dev_token(user_id, email=f"demo-{body.role}@example.com"))


@router.post("/demo/seed")
def demo_seed(session: DbSession) -> dict:
    """Idempotently create the demo workspace, apps, FAQ catalog, pricing and default policy."""
    _require_demo()
    ws = bootstrap_demo(session)
    return {"workspace_id": str(ws.id), "status": "seeded"}


@router.post("/demo/reset")
def demo_reset(principal: CurrentUser, session: DbSession) -> dict:
    """Owner-only: clear operational data for the demo workspace. The audit log is kept (immutable)."""
    _require_demo()
    m = require_member(session, principal, None, role="owner")
    ws_id = m.workspace_id
    for model in (
        Recommendation,
        ScenarioRun,
        ForecastRun,
        AnomalyEvent,
        ResponseCache,
        DailyUsage,
        ApiRequest,
    ):
        session.execute(delete(model).where(model.workspace_id == ws_id))
    session.execute(
        update(Policy)
        .where(Policy.workspace_id == ws_id)
        .values(enabled=False, approved_by=None, approved_at=None, version=Policy.version + 1)
    )
    session.add(PolicyAudit(workspace_id=ws_id, actor_user_id=principal.user_id, action="demo_reset"))
    session.commit()
    return {"workspace_id": str(ws_id), "status": "reset"}
