"""Temporal retrieval data access — reads the canonical temporal stores (Module-1 media + Module-3
tintel) workspace-scoped, plus the `TemporalSearchLog` writes + stats. No new retrieval storage.

Mirrors `mmretrieval.RetrievalRepository`: retrievers get candidate rows from here; the orchestrator
scores/fuses them. Media models (TranscriptSegment/Speaker/Scene/MediaFrame/Subtitle/MediaChunk) and
tintel models (Chapter/Topic/TimelineEvent) are imported lazily inside methods to keep this importable
without forcing model import order.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.tretrieval.models import TemporalSearchLog


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TemporalRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ media candidate reads
    def segments(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 2000):
        from app.media.models import TranscriptSegment
        stmt = select(TranscriptSegment).where(TranscriptSegment.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(TranscriptSegment.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def speakers(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 500):
        from app.media.models import Speaker
        stmt = select(Speaker).where(Speaker.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(Speaker.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def scenes(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 1000):
        from app.media.models import Scene
        stmt = select(Scene).where(Scene.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(Scene.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def frames(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 2000):
        from app.media.models import MediaFrame
        stmt = select(MediaFrame).where(MediaFrame.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(MediaFrame.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def subtitles(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 2000):
        from app.media.models import Subtitle
        stmt = select(Subtitle).where(Subtitle.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(Subtitle.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    # ------------------------------------------------------------------ tintel candidate reads
    def chapters(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 1000):
        from app.tintel.models import Chapter
        stmt = select(Chapter).where(Chapter.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(Chapter.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def topics(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 1000):
        from app.tintel.models import Topic
        stmt = select(Topic).where(Topic.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(Topic.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def events(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 2000):
        from app.tintel.models import TimelineEvent
        stmt = select(TimelineEvent).where(TimelineEvent.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(TimelineEvent.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def speaker_label(self, speaker_id: Optional[str]) -> str:
        if not speaker_id:
            return ""
        from app.media.models import Speaker
        row = self.db.scalar(select(Speaker).where(Speaker.id == speaker_id))
        return row.speaker_label if row else ""

    # ------------------------------------------------------------------ processed-media docs (for ensure_derived)
    def processed_media_docs(self, workspace_id: str, owner_id: str, document_id: Optional[str] = None):
        from app.media.models import MediaJob
        stmt = select(MediaJob.document_id).where(
            MediaJob.workspace_id == workspace_id, MediaJob.owner_id == owner_id,
            MediaJob.status == "completed")
        if document_id:
            stmt = stmt.where(MediaJob.document_id == document_id)
        return sorted(set(self.db.scalars(stmt)))

    # ------------------------------------------------------------------ observability
    def log_search(self, log: TemporalSearchLog) -> None:
        self.db.add(log)
        self.db.commit()

    def indexed_counts(self, workspace_id: str) -> Dict[str, int]:
        from app.media.models import MediaFrame, Scene, Subtitle, TranscriptSegment
        from app.tintel.models import Chapter, TimelineEvent, Topic

        def c(model):
            return int(self.db.scalar(select(func.count()).select_from(model)
                                      .where(model.workspace_id == workspace_id)) or 0)
        return {"transcript_segments": c(TranscriptSegment), "scenes": c(Scene), "frames": c(MediaFrame),
                "subtitles": c(Subtitle), "chapters": c(Chapter), "topics": c(Topic),
                "events": c(TimelineEvent)}

    def stats(self, workspace_id: str, *, limit_recent: int = 10) -> Dict:
        total = int(self.db.scalar(select(func.count()).select_from(TemporalSearchLog)
                                   .where(TemporalSearchLog.workspace_id == workspace_id)) or 0)
        avg = float(self.db.scalar(select(func.coalesce(func.avg(TemporalSearchLog.total_ms), 0.0))
                                   .where(TemporalSearchLog.workspace_id == workspace_id)) or 0.0)
        rows = list(self.db.scalars(select(TemporalSearchLog)
                                    .where(TemporalSearchLog.workspace_id == workspace_id)
                                    .order_by(desc(TemporalSearchLog.created_at)).limit(200)))
        usage: Dict[str, int] = {}
        for r in rows:
            for m in (r.intents or []):
                usage[m] = usage.get(m, 0) + 1
        recent = [r.query for r in rows[:limit_recent]]
        return {"searches": total, "avg_latency_ms": round(avg, 2), "modality_usage": usage,
                "recent_queries": recent}
