"""Workspace activity feed recording and listing.

Every significant action is recorded as an immutable event. The feed is the workspace's
timeline — "who did what, and when."
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.collaboration.activity_repository import ActivityRepository
from app.collaboration.models import ActivityEvent


class ActivityService:

    def __init__(self, repo: ActivityRepository | None = None):
        self.repo = repo or ActivityRepository()

    def record(
        self,
        db: Session,
        *,
        workspace_id: str,
        actor_id: str,
        event_type: str,
        description: str = "",
        target_type: str | None = None,
        target_id: str | None = None,
        target_title: str | None = None,
        details: dict | None = None,
    ) -> ActivityEvent:
        event = ActivityEvent(
            workspace_id=workspace_id,
            actor_id=actor_id,
            event_type=event_type,
            description=description,
            target_type=target_type,
            target_id=target_id,
            target_title=target_title,
            details=details,
        )
        self.repo.create(db, event)
        db.commit()
        return event

    def list_for_workspace(
        self,
        db: Session,
        workspace_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
    ) -> list[ActivityEvent]:
        return self.repo.list_for_workspace(
            db, workspace_id, limit=limit, offset=offset, event_type=event_type
        )

    def count(self, db: Session, workspace_id: str) -> int:
        return self.repo.count_for_workspace(db, workspace_id)
