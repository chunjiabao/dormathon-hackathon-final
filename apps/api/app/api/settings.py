import secrets
import uuid
from decimal import Decimal

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.chat import hash_app_key
from app.auth import CurrentUser, DbSession, require_member
from app.config import get_settings
from app.errors import ApiError
from app.models import ApiRequest, Application, DailyUsage, PolicyAudit, Workspace, WorkspaceMember
from app.schemas import (
    ApplicationOut,
    MembershipOut,
    MeResponse,
    RotatedKeyResponse,
    WorkspaceSettings,
    WorkspaceSettingsPatch,
)

router = APIRouter(tags=["settings"])


@router.get("/me", response_model=MeResponse)
def me(principal: CurrentUser, session: DbSession) -> MeResponse:
    rows = session.execute(
        select(WorkspaceMember.workspace_id, Workspace.name, WorkspaceMember.role)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.auth_user_id == principal.user_id)
        .order_by(Workspace.name)
    ).all()
    return MeResponse(
        user_id=principal.user_id,
        email=principal.email,
        memberships=[MembershipOut(workspace_id=w, workspace_name=n, role=r) for w, n, r in rows],
    )


def _settings_out(session: DbSession, ws: Workspace, role: str) -> WorkspaceSettings:
    s = get_settings()
    apps = session.scalars(select(Application).where(Application.workspace_id == ws.id).order_by(Application.name))
    real = session.scalar(select(func.count()).select_from(ApiRequest).where(ApiRequest.workspace_id == ws.id))
    synthetic_days = session.scalar(
        select(func.count(func.distinct(DailyUsage.day))).where(
            DailyUsage.workspace_id == ws.id, DailyUsage.data_origin == "synthetic"
        )
    )
    return WorkspaceSettings(
        workspace_id=ws.id,
        name=ws.name,
        monthly_budget_myr=float(ws.monthly_budget_myr),
        currency=ws.currency,
        timezone=ws.timezone,
        knowledge_version=ws.knowledge_version,
        role=role,
        applications=[
            ApplicationOut(id=a.id, name=a.name, is_active=a.is_active, has_api_key=a.app_key_hash is not None)
            for a in apps
        ],
        data_sources={"real_requests": real or 0, "synthetic_days": synthetic_days or 0},
        provider_mode=s.provider_mode,
        fx_myr_per_usd_demo=s.myr_per_usd_demo,
        pricing_catalog_version=s.pricing_catalog_version,
    )


@router.get("/settings/workspace", response_model=WorkspaceSettings)
def get_workspace_settings(
    principal: CurrentUser, session: DbSession, workspace_id: uuid.UUID | None = None
) -> WorkspaceSettings:
    m = require_member(session, principal, workspace_id)
    return _settings_out(session, session.get(Workspace, m.workspace_id), m.role)


@router.patch("/settings/workspace", response_model=WorkspaceSettings)
def patch_workspace_settings(
    body: WorkspaceSettingsPatch,
    principal: CurrentUser,
    session: DbSession,
    workspace_id: uuid.UUID | None = None,
) -> WorkspaceSettings:
    m = require_member(session, principal, workspace_id, role="owner")
    ws = session.get(Workspace, m.workspace_id)
    old = {"monthly_budget_myr": float(ws.monthly_budget_myr), "timezone": ws.timezone}
    if body.monthly_budget_myr is not None:
        ws.monthly_budget_myr = Decimal(str(body.monthly_budget_myr))
    if body.timezone is not None:
        from zoneinfo import available_timezones

        if body.timezone not in available_timezones():
            raise ApiError(422, "validation_error", "Unknown timezone.")
        ws.timezone = body.timezone
    new = {"monthly_budget_myr": float(ws.monthly_budget_myr), "timezone": ws.timezone}
    if new != old:
        session.add(
            PolicyAudit(
                workspace_id=ws.id,
                actor_user_id=principal.user_id,
                action="settings_update",
                old_value=old,
                new_value=new,
            )
        )
    session.commit()
    return _settings_out(session, ws, m.role)


@router.post("/applications/{application_id}/rotate-key", response_model=RotatedKeyResponse)
def rotate_app_key(application_id: uuid.UUID, principal: CurrentUser, session: DbSession) -> RotatedKeyResponse:
    app = session.get(Application, application_id)
    if app is None:
        raise ApiError(404, "not_found", "Application not found.")
    require_member(session, principal, app.workspace_id, role="owner")
    key = f"tg_{secrets.token_urlsafe(32)}"
    had_key = app.app_key_hash is not None
    app.app_key_hash = hash_app_key(key)
    session.add(
        PolicyAudit(
            workspace_id=app.workspace_id,
            application_id=app.id,
            actor_user_id=principal.user_id,
            action="api_key_rotated",
            old_value={"had_key": had_key},
            new_value={"had_key": True},
        )
    )
    session.commit()
    return RotatedKeyResponse(application_id=app.id, api_key=key)
