from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import DailyUsage, Workspace
from app.services.history import aggregate_real_usage
from app.services.retention import purge_expired


def test_retention_preserves_synthetic_and_other_tenant_history(session, bakery_app, other_app):
    now = datetime(2026, 10, 11, tzinfo=UTC)
    ws = session.get(Workspace, bakery_app.workspace_id)
    old = now.date() - timedelta(days=200)
    rows = []
    for app, origin, day in (
        (bakery_app, "real", old),
        (bakery_app, "synthetic", old),
        (other_app, "real", old),
        (bakery_app, "real", now.date() - timedelta(days=60)),
    ):
        row = DailyUsage(
            workspace_id=app.workspace_id,
            application_id=app.id,
            day=day,
            request_category="static_faq",
            model="retention-test",
            requests=1,
            input_tokens=1,
            output_tokens=1,
            cost_myr=0.01,
            cache_hits=0,
            retry_requests=0,
            data_origin=origin,
        )
        session.add(row)
        rows.append(row)
    session.commit()
    ids = [r.id for r in rows]
    result = purge_expired(session, ws, now=now)
    assert result["real_aggregates"] >= 1
    retained = set(session.scalars(select(DailyUsage.id).where(DailyUsage.id.in_(ids))))
    assert ids[0] not in retained
    assert set(ids[1:]) <= retained
    # Expired request metadata must not erase the longer-lived daily totals.
    aggregate_real_usage(session, ws, through=now.date())
    assert session.get(DailyUsage, ids[3]) is not None
    for row_id in ids[1:]:
        session.delete(session.get(DailyUsage, row_id))
    session.commit()
