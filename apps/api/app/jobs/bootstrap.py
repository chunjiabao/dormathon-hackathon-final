"""Idempotent workspace bootstrap, safe to run on every deploy.

    uv run python -m app.jobs.bootstrap

Creates the demo workspace, apps, FAQ catalog, pricing and the (disabled) cache policy. If
OWNER_AUTH_USER_ID is set (a Supabase Auth user UUID), that user is added as workspace owner,
which is how a real account gets owner rights in hosted mode.
"""

import os
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import WorkspaceMember
from app.services.seed import bootstrap_demo


def main() -> None:
    with Session(get_engine()) as session:
        ws = bootstrap_demo(session)
        owner = os.environ.get("OWNER_AUTH_USER_ID")
        if owner:
            user_id = uuid.UUID(owner)
            exists = session.scalar(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == ws.id, WorkspaceMember.auth_user_id == user_id
                )
            )
            if not exists:
                session.add(WorkspaceMember(workspace_id=ws.id, auth_user_id=user_id, role="owner"))
                session.commit()
        print(f"bootstrap ok: workspace {ws.slug} ({ws.id})")


if __name__ == "__main__":
    main()
