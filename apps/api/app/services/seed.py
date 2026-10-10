"""Idempotent bootstrap of the demo workspace, applications, FAQ catalog, pricing and default policy.

Synthetic usage history is loaded separately (Phase 2) and always labelled data_origin='synthetic'.
"""

import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, FaqEntry, Policy, PricingCatalog, Workspace, WorkspaceMember

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

DEMO_WORKSPACE_SLUG = "sweet-crumbs"
# Fixed demo identities for local dev-login. Hosted mode maps real Supabase users via workspace_members.
DEMO_OWNER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEMO_VIEWER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
DEMO_APPS = ("bakery_demo", "tuition_demo", "retail_demo")
CHAT_APP = "bakery_demo"
FAQ_FIXTURES = {"bakery_demo": "bakery_faq.json", "tuition_demo": "tuition_faq.json", "retail_demo": "retail_faq.json"}


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def ensure_pricing(session: Session) -> None:
    data = load_json("pricing.json")
    for m in data["models"]:
        exists = session.scalar(
            select(PricingCatalog.id).where(
                PricingCatalog.provider == m["provider"],
                PricingCatalog.model == m["model"],
                PricingCatalog.version == data["version"],
            )
        )
        if exists:
            continue
        session.add(
            PricingCatalog(
                provider=m["provider"],
                model=m["model"],
                effective_from=date.fromisoformat(m["effective_from"]),
                input_usd_per_million=Decimal(str(m["input_usd_per_million"])),
                output_usd_per_million=Decimal(str(m["output_usd_per_million"])),
                cache_read_usd_per_million=Decimal(str(m["cache_read_usd_per_million"])),
                cache_write_usd_per_million=Decimal(str(m["cache_write_usd_per_million"])),
                source_url=m["source_url"],
                verified_at=None,
                version=data["version"],
            )
        )


def ensure_faq(session: Session, ws: Workspace, app: Application, fixture: str = "bakery_faq.json") -> None:
    data = load_json(fixture)
    for e in data["entries"]:
        exists = session.scalar(
            select(FaqEntry.id).where(
                FaqEntry.application_id == app.id,
                FaqEntry.intent_key == e["intent_key"],
                FaqEntry.locale == data["locale"],
                FaqEntry.knowledge_version == ws.knowledge_version,
            )
        )
        if exists:
            continue
        session.add(
            FaqEntry(
                workspace_id=ws.id,
                application_id=app.id,
                intent_key=e["intent_key"],
                question=e["question"],
                approved_answer=e["answer"],
                aliases=e["aliases"],
                locale=data["locale"],
                knowledge_version=ws.knowledge_version,  # (re)publish approved FAQ at the current version
                cacheable=True,
            )
        )


def ensure_workspace(
    session: Session,
    slug: str = DEMO_WORKSPACE_SLUG,
    name: str = "Sweet Crumbs Bakery (demo)",
    owner_id: uuid.UUID = DEMO_OWNER_ID,
    viewer_id: uuid.UUID | None = DEMO_VIEWER_ID,
) -> Workspace:
    """Create (or fetch) a workspace with members, demo apps, FAQ and a disabled cache policy."""
    ws = session.scalar(select(Workspace).where(Workspace.slug == slug))
    if ws is None:
        ws = Workspace(name=name, slug=slug, monthly_budget_myr=Decimal(str(get_settings().monthly_budget_myr_default)))
        session.add(ws)
        session.flush()
    members = [(owner_id, "owner")] + ([(viewer_id, "viewer")] if viewer_id else [])
    for user_id, role in members:
        if not session.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == ws.id, WorkspaceMember.auth_user_id == user_id
            )
        ):
            session.add(WorkspaceMember(workspace_id=ws.id, auth_user_id=user_id, role=role))
    for app_name in DEMO_APPS:
        app = session.scalar(select(Application).where(Application.workspace_id == ws.id, Application.name == app_name))
        if app is None:
            app = Application(workspace_id=ws.id, name=app_name, is_active=True)
            session.add(app)
            session.flush()
        if app_name in FAQ_FIXTURES:
            ensure_faq(session, ws, app, FAQ_FIXTURES[app_name])
            if not session.scalar(
                select(Policy.id).where(Policy.application_id == app.id, Policy.policy_type == "semantic_cache")
            ):
                # Off by default: caching is only enabled through explicit owner approval.
                session.add(Policy(workspace_id=ws.id, application_id=app.id, policy_type="semantic_cache"))
    session.flush()
    return ws


def bootstrap_demo(session: Session) -> Workspace:
    ensure_pricing(session)
    ws = ensure_workspace(session)
    session.commit()
    return ws


def chat_application(session: Session, workspace_id: uuid.UUID | None = None) -> Application | None:
    stmt = select(Application).join(Workspace).where(Application.name == CHAT_APP)
    if workspace_id is None:
        stmt = stmt.where(Workspace.slug == DEMO_WORKSPACE_SLUG)
    else:
        stmt = stmt.where(Application.workspace_id == workspace_id)
    return session.scalar(stmt)
