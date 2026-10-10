import base64
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from app.auth import CurrentUser, DbSession, require_member
from app.errors import ApiError
from app.models import ApiRequest, DailyUsage
from app.services.history import app_maps

router = APIRouter(tags=["usage"])


@router.get("/usage/daily")
def usage_daily(
    principal: CurrentUser,
    session: DbSession,
    workspace_id: uuid.UUID | None = None,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    data_origin: str | None = Query(default=None, pattern="^(real|synthetic)$"),
) -> dict:
    """Daily aggregates with explicit origin labels (synthetic and real are never merged here)."""
    m = require_member(session, principal, workspace_id)
    if from_ and to and from_ > to:
        raise ApiError(422, "validation_error", "From date must be on or before To date.")
    id_to_name, _ = app_maps(session, m.workspace_id)
    stmt = select(
        DailyUsage.day, DailyUsage.application_id, DailyUsage.request_category, DailyUsage.model,
        DailyUsage.data_origin, DailyUsage.requests, DailyUsage.input_tokens, DailyUsage.output_tokens,
        DailyUsage.cost_myr, DailyUsage.cache_hits, DailyUsage.retry_requests,
    ).where(DailyUsage.workspace_id == m.workspace_id)  # fmt: skip
    if from_:
        stmt = stmt.where(DailyUsage.day >= from_)
    if to:
        stmt = stmt.where(DailyUsage.day <= to)
    if data_origin:
        stmt = stmt.where(DailyUsage.data_origin == data_origin)
    rows = session.execute(stmt.order_by(DailyUsage.day)).all()
    items = [
        {"day": str(r.day), "application": id_to_name.get(r.application_id), "request_category": r.request_category,
         "model": r.model, "data_origin": r.data_origin, "requests": r.requests, "input_tokens": r.input_tokens,
         "output_tokens": r.output_tokens, "cost_myr": float(r.cost_myr), "cache_hits": r.cache_hits,
         "retry_requests": r.retry_requests}
        for r in rows
    ]  # fmt: skip
    return {
        "items": items,
        "next_cursor": None,
        "currency": "MYR",
        "cost_note": "Estimated from token counts.",
    }


def _encode(ts: datetime, rid: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{ts.isoformat()}|{rid}".encode()).decode()


def _decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        ts, rid = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(ts), uuid.UUID(rid)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(422, "validation_error", "Invalid cursor.") from exc


@router.get("/usage/requests")
def usage_requests(
    principal: CurrentUser,
    session: DbSession,
    workspace_id: uuid.UUID | None = None,
    cursor: str | None = None,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    application: str | None = None,
    model: str | None = None,
    request_category: str | None = None,
    data_origin: str | None = Query(default=None, pattern="^(real|synthetic)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """Safe request metadata only: no message text is stored or returned."""
    m = require_member(session, principal, workspace_id)
    id_to_name, _ = app_maps(session, m.workspace_id)
    if from_ and to and from_ > to:
        raise ApiError(422, "validation_error", "From date must be on or before To date.")
    filters = [ApiRequest.workspace_id == m.workspace_id]
    if application:
        app_ids = [aid for aid, name in id_to_name.items() if name == application]
        filters.append(ApiRequest.application_id.in_(app_ids))
    for column, value in (
        (ApiRequest.model, model),
        (ApiRequest.request_category, request_category),
        (ApiRequest.data_origin, data_origin),
    ):
        if value:
            filters.append(column == value)
    tz = ZoneInfo("Asia/Kuala_Lumpur")
    if from_:
        filters.append(ApiRequest.occurred_at >= datetime.combine(from_, datetime.min.time(), tz).astimezone(UTC))
    if to:
        filters.append(
            ApiRequest.occurred_at < datetime.combine(to + timedelta(days=1), datetime.min.time(), tz).astimezone(UTC)
        )
    stmt = select(ApiRequest).where(*filters)
    if cursor:
        ts, rid = _decode(cursor)
        stmt = stmt.where(or_(ApiRequest.occurred_at < ts, and_(ApiRequest.occurred_at == ts, ApiRequest.id < rid)))
    rows = list(session.scalars(stmt.order_by(ApiRequest.occurred_at.desc(), ApiRequest.id.desc()).limit(limit + 1)))
    page, more = rows[:limit], len(rows) > limit
    total = session.scalar(select(func.count()).select_from(ApiRequest).where(*filters))
    return {
        "items": [
            {
                "id": str(r.id),
                "occurred_at": r.occurred_at.isoformat(),
                "application": id_to_name.get(r.application_id),
                "provider": r.provider,
                "provider_mode": "mock" if r.provider.endswith("-mock") else "live",
                "model": r.model,
                "request_category": r.request_category,
                "cache_status": r.cache_status,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "estimated_cost_myr": float(r.estimated_cost_myr),
                "latency_ms": r.latency_ms,
                "data_origin": r.data_origin,
                "faq_intent_key": r.faq_intent_key,
                "similarity_score": float(r.similarity_score) if r.similarity_score is not None else None,
                "error_code": r.error_code,
            }
            for r in page
        ],  # fmt: skip
        "next_cursor": _encode(page[-1].occurred_at, page[-1].id) if more else None,
        "total": total,
    }
