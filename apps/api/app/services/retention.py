"""Bounded retention after aggregation. Never delete policies, forecasts or immutable audit rows."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ApiRequest, DailyUsage, ResponseCache, Workspace


def purge_expired(session: Session, ws: Workspace, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    cfg = get_settings()
    tz = ZoneInfo(ws.timezone)
    request_day = now.astimezone(tz).date() - timedelta(days=cfg.request_retention_days)
    oldest_request = datetime.combine(request_day, time.min, tzinfo=tz)
    oldest_day = now.astimezone(ZoneInfo(ws.timezone)).date() - timedelta(days=cfg.aggregate_retention_days)
    filters = (
        ("request_metadata", ApiRequest, (ApiRequest.workspace_id == ws.id, ApiRequest.occurred_at < oldest_request)),
        (
            "real_aggregates",
            DailyUsage,
            (DailyUsage.workspace_id == ws.id, DailyUsage.data_origin == "real", DailyUsage.day < oldest_day),
        ),
        ("expired_cache", ResponseCache, (ResponseCache.workspace_id == ws.id, ResponseCache.expires_at <= now)),
    )
    result = {label: session.execute(delete(model).where(*conditions)).rowcount for label, model, conditions in filters}
    session.commit()
    return result
