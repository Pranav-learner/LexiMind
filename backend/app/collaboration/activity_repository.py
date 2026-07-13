"""Data-access layer for the ActivityEvent table."""

from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.collaboration.models import ActivityEvent


class ActivityRepository:

    @staticmethod
    def create(db: Session, event: ActivityEvent) -> ActivityEvent:
        db.add(event)
        db.flush()
        return event

    @staticmethod
    def list_for_workspace(
        db: Session,
        workspace_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
    ) -> list[ActivityEvent]:
        q = select(ActivityEvent).where(
            ActivityEvent.workspace_id == workspace_id,
        )
        if event_type:
            q = q.where(ActivityEvent.event_type == event_type)
        return list(
            db.scalars(
                q.order_by(ActivityEvent.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    @staticmethod
    def count_for_workspace(db: Session, workspace_id: str) -> int:
        return db.scalar(
            select(func.count()).select_from(ActivityEvent).where(
                ActivityEvent.workspace_id == workspace_id,
            )
        ) or 0

    @staticmethod
    def list_for_actor(
        db: Session,
        actor_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ActivityEvent]:
        return list(
            db.scalars(
                select(ActivityEvent)
                .where(ActivityEvent.actor_id == actor_id)
                .order_by(ActivityEvent.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
