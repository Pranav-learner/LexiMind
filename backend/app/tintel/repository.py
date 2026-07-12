"""Temporal-intelligence data access — the ONLY place that issues SQL for the canonical
chapter/topic/event tables. Also reads Module-1 media rows needed for derivation (workspace-scoped),
mirroring how `mmretrieval` reads ingestion/vision models directly."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import asc, delete, func, select
from sqlalchemy.orm import Session

from app.tintel.models import Chapter, TimelineEvent, Topic


class TemporalIntelRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ media reads (for derivation)
    def segments(self, document_id: str):
        from app.media.models import TranscriptSegment
        return list(self.db.scalars(
            select(TranscriptSegment).where(TranscriptSegment.document_id == document_id)
            .order_by(asc(TranscriptSegment.start_ms))))

    def turns(self, document_id: str):
        from app.media.models import SpeakerTurn
        return list(self.db.scalars(
            select(SpeakerTurn).where(SpeakerTurn.document_id == document_id)
            .order_by(asc(SpeakerTurn.start_ms))))

    def scenes(self, document_id: str):
        from app.media.models import Scene
        return list(self.db.scalars(
            select(Scene).where(Scene.document_id == document_id).order_by(asc(Scene.start_ms))))

    def latest_job(self, document_id: str):
        from app.media.models import MediaJob
        return self.db.scalar(select(MediaJob).where(MediaJob.document_id == document_id)
                              .order_by(MediaJob.created_at.desc()).limit(1))

    # ------------------------------------------------------------------ canonical writes
    def clear(self, document_id: str) -> None:
        for model in (Chapter, Topic, TimelineEvent):
            self.db.execute(delete(model).where(model.document_id == document_id))
        self.db.commit()

    def add_all(self, rows: List) -> int:
        if rows:
            self.db.add_all(rows)
            self.db.commit()
        return len(rows)

    # ------------------------------------------------------------------ canonical reads
    def chapters(self, document_id: str) -> List[Chapter]:
        return list(self.db.scalars(select(Chapter).where(Chapter.document_id == document_id)
                                    .order_by(asc(Chapter.start_ms))))

    def topics(self, document_id: str) -> List[Topic]:
        return list(self.db.scalars(select(Topic).where(Topic.document_id == document_id)
                                    .order_by(asc(Topic.start_ms))))

    def events(self, document_id: str, event_type: Optional[str] = None) -> List[TimelineEvent]:
        stmt = select(TimelineEvent).where(TimelineEvent.document_id == document_id)
        if event_type:
            stmt = stmt.where(TimelineEvent.event_type == event_type)
        return list(self.db.scalars(stmt.order_by(asc(TimelineEvent.timestamp_ms))))

    # workspace-scoped reads (used by temporal retrieval across all recordings)
    def chapters_ws(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 1000):
        stmt = select(Chapter).where(Chapter.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(Chapter.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def topics_ws(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 1000):
        stmt = select(Topic).where(Topic.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(Topic.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def events_ws(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 2000):
        stmt = select(TimelineEvent).where(TimelineEvent.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(TimelineEvent.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def count(self, document_id: str) -> int:
        def c(model):
            return int(self.db.scalar(select(func.count()).select_from(model)
                                      .where(model.document_id == document_id)) or 0)
        return c(Chapter) + c(Topic) + c(TimelineEvent)
