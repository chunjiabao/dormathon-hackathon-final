"""Workspace usage history loading and daily aggregation of real gateway traffic."""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ml.clean import daily_from_requests
from app.models import ApiRequest, Application, DailyUsage, Workspace

DAILY_COLUMNS = [
    "day", "app_id", "request_category", "model", "requests", "input_tokens", "output_tokens",
    "cost_myr", "cache_hits", "retry_requests", "data_origin",
]  # fmt: skip


def app_maps(session: Session, workspace_id: uuid.UUID) -> tuple[dict[uuid.UUID, str], dict[str, uuid.UUID]]:
    apps = session.execute(
        select(Application.id, Application.name).where(Application.workspace_id == workspace_id)
    ).all()
    return {i: n for i, n in apps}, {n: i for i, n in apps}


def load_daily(session: Session, workspace_id: uuid.UUID, before: date | None = None) -> pd.DataFrame:
    """Daily usage for the workspace (both origins), app_id holding the application *name*."""
    stmt = select(DailyUsage).where(DailyUsage.workspace_id == workspace_id)
    if before is not None:
        stmt = stmt.where(DailyUsage.day < before)
    id_to_name, _ = app_maps(session, workspace_id)
    rows = [
        (r.day, id_to_name[r.application_id], r.request_category, r.model, r.requests, r.input_tokens,
         r.output_tokens, float(r.cost_myr), r.cache_hits, r.retry_requests, r.data_origin)
        for r in session.scalars(stmt)
    ]  # fmt: skip
    return pd.DataFrame(rows, columns=DAILY_COLUMNS)


def aggregate_real_usage(session: Session, ws: Workspace, through: date) -> int:
    """Rebuild data_origin='real' daily_usage rows from api_requests for complete days <= through.

    Errors (no provider usage) are excluded; cache hits count as requests with zero provider cost.
    """
    tz = ZoneInfo(ws.timezone)
    end_utc = datetime.combine(through + timedelta(days=1), time.min, tzinfo=tz)
    reqs = session.execute(
        select(
            ApiRequest.id, ApiRequest.application_id, ApiRequest.occurred_at, ApiRequest.request_category,
            ApiRequest.model, ApiRequest.input_tokens, ApiRequest.output_tokens, ApiRequest.estimated_cost_myr,
            ApiRequest.cache_status, ApiRequest.request_fingerprint, ApiRequest.client_fingerprint,
        ).where(
            ApiRequest.workspace_id == ws.id, ApiRequest.occurred_at < end_utc,
            ApiRequest.cache_status != "error", ApiRequest.data_origin == "real",
        )
    ).all()  # fmt: skip
    if not reqs:
        session.commit()
        return 0
    df = pd.DataFrame(
        reqs,
        columns=["request_id", "app_id", "occurred_at", "request_category", "model", "input_tokens",
                 "output_tokens", "cost_myr", "cache_status", "fingerprint", "client_fingerprint"],
    )  # fmt: skip
    df["cost_myr"] = df.cost_myr.astype(float)
    df["occurred_at"] = pd.to_datetime(df.occurred_at, utc=True)
    df["day"] = df.occurred_at.dt.tz_convert(tz).dt.date
    daily = daily_from_requests(df, data_origin="real")
    first_day = df.day.min()
    session.execute(
        delete(DailyUsage).where(
            DailyUsage.workspace_id == ws.id,
            DailyUsage.data_origin == "real",
            DailyUsage.day >= first_day,
            DailyUsage.day <= through,
        )
    )
    for r in daily.itertuples():
        session.add(
            DailyUsage(
                workspace_id=ws.id, application_id=r.app_id, day=r.day, request_category=r.request_category,
                model=r.model, requests=int(r.requests), input_tokens=int(r.input_tokens),
                output_tokens=int(r.output_tokens), cost_myr=round(float(r.cost_myr), 6),
                cache_hits=int(r.cache_hits), retry_requests=int(r.retry_requests), data_origin="real",
            )
        )  # fmt: skip
    session.commit()
    return len(daily)
