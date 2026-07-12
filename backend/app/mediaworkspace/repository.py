"""Media AI Workspace data access — ONLY the interaction-telemetry table. Everything else is read
through the existing domain repositories (reuse, never duplicate)."""

from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.mediaworkspace.models import MediaInteractionEvent


class MediaWorkspaceRepository:
    def __init__(self, db: Session):
        self.db = db

    def record(self, ev: MediaInteractionEvent) -> MediaInteractionEvent:
        self.db.add(ev)
        self.db.commit()
        self.db.refresh(ev)
        return ev

    def usage(self, workspace_id: str) -> Dict[str, int]:
        rows = self.db.execute(
            select(MediaInteractionEvent.event_type, func.count())
            .where(MediaInteractionEvent.workspace_id == workspace_id)
            .group_by(MediaInteractionEvent.event_type)
        ).all()
        return {etype: int(n) for etype, n in rows}

    def recent(self, workspace_id: str, limit: int = 20) -> List[MediaInteractionEvent]:
        return list(self.db.scalars(
            select(MediaInteractionEvent).where(MediaInteractionEvent.workspace_id == workspace_id)
            .order_by(desc(MediaInteractionEvent.created_at)).limit(limit)))

    def total(self, workspace_id: str, event_type: Optional[str] = None) -> int:
        stmt = select(func.count()).select_from(MediaInteractionEvent).where(
            MediaInteractionEvent.workspace_id == workspace_id)
        if event_type:
            stmt = stmt.where(MediaInteractionEvent.event_type == event_type)
        return int(self.db.scalar(stmt) or 0)
