"""Media data access — the ONLY place that issues SQL for the media tables.

Owner/workspace scoping is enforced by the service (which passes `owner_id`); this layer is a thin,
well-indexed query surface. Frame-OCR caching reuses the Phase-4 `OcrResult` table via
`app.ingestion.repository.IngestionRepository` (no duplicate cache).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import asc, delete, desc, func, select
from sqlalchemy.orm import Session

from app.media.models import (
    MediaChunk,
    MediaFrame,
    MediaJob,
    MediaProcessingLog,
    Scene,
    Speaker,
    SpeakerTurn,
    Subtitle,
    TranscriptSegment,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MediaRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ jobs
    def get_job(self, job_id: str, owner_id: str) -> Optional[MediaJob]:
        return self.db.scalar(select(MediaJob).where(MediaJob.id == job_id, MediaJob.owner_id == owner_id))

    def get_job_by_id_only(self, job_id: str) -> Optional[MediaJob]:
        return self.db.scalar(select(MediaJob).where(MediaJob.id == job_id))

    def latest_job_for_document(self, document_id: str, owner_id: str) -> Optional[MediaJob]:
        return self.db.scalar(
            select(MediaJob).where(MediaJob.document_id == document_id, MediaJob.owner_id == owner_id)
            .order_by(desc(MediaJob.created_at)).limit(1)
        )

    def create_job(self, job: MediaJob) -> MediaJob:
        self.db.add(job); self.db.commit(); self.db.refresh(job); return job

    def save_job(self, job: MediaJob) -> MediaJob:
        job.updated_at = _now(); self.db.commit(); self.db.refresh(job); return job

    def job_status(self, job_id: str) -> Optional[str]:
        """Read ONLY the status column (used for cancellation checks without refreshing the row)."""
        return self.db.scalar(select(MediaJob.status).where(MediaJob.id == job_id))

    # ------------------------------------------------------------------ logs
    def log(self, job: MediaJob, stage: str, message: str, level: str = "info") -> None:
        self.db.add(MediaProcessingLog(job_id=job.id, workspace_id=job.workspace_id, stage=stage,
                                       level=level, message=message[:2000]))
        self.db.commit()

    def logs_for(self, job_id: str) -> List[MediaProcessingLog]:
        return list(self.db.scalars(
            select(MediaProcessingLog).where(MediaProcessingLog.job_id == job_id)
            .order_by(asc(MediaProcessingLog.created_at))))

    # ------------------------------------------------------------------ bulk inserts
    def add_segments(self, rows: List[TranscriptSegment]) -> int:
        if rows:
            self.db.add_all(rows); self.db.commit()
        return len(rows)

    def add_speakers(self, rows: List[Speaker]) -> int:
        if rows:
            self.db.add_all(rows); self.db.commit()
        return len(rows)

    def add_turns(self, rows: List[SpeakerTurn]) -> int:
        if rows:
            self.db.add_all(rows); self.db.commit()
        return len(rows)

    def add_frame(self, row: MediaFrame) -> MediaFrame:
        self.db.add(row); self.db.commit(); self.db.refresh(row); return row

    def add_scenes(self, rows: List[Scene]) -> int:
        if rows:
            self.db.add_all(rows); self.db.commit()
        return len(rows)

    def add_subtitles(self, rows: List[Subtitle]) -> int:
        if rows:
            self.db.add_all(rows); self.db.commit()
        return len(rows)

    def add_chunks(self, rows: List[MediaChunk]) -> int:
        if rows:
            self.db.add_all(rows); self.db.commit()
        return len(rows)

    def save(self) -> None:
        self.db.commit()

    # ------------------------------------------------------------------ reads
    def segments_for(self, document_id: str, speaker_id: Optional[str] = None) -> List[TranscriptSegment]:
        stmt = select(TranscriptSegment).where(TranscriptSegment.document_id == document_id)
        if speaker_id:
            stmt = stmt.where(TranscriptSegment.speaker_id == speaker_id)
        return list(self.db.scalars(stmt.order_by(asc(TranscriptSegment.start_ms))))

    def speakers_for(self, document_id: str) -> List[Speaker]:
        return list(self.db.scalars(
            select(Speaker).where(Speaker.document_id == document_id).order_by(asc(Speaker.speaker_label))))

    def turns_for(self, document_id: str) -> List[SpeakerTurn]:
        return list(self.db.scalars(
            select(SpeakerTurn).where(SpeakerTurn.document_id == document_id).order_by(asc(SpeakerTurn.start_ms))))

    def frames_for(self, document_id: str, scene_id: Optional[str] = None) -> List[MediaFrame]:
        stmt = select(MediaFrame).where(MediaFrame.document_id == document_id)
        if scene_id:
            stmt = stmt.where(MediaFrame.scene_id == scene_id)
        return list(self.db.scalars(stmt.order_by(asc(MediaFrame.timestamp_ms))))

    def frame(self, frame_id: str) -> Optional[MediaFrame]:
        return self.db.scalar(select(MediaFrame).where(MediaFrame.id == frame_id))

    def scenes_for(self, document_id: str) -> List[Scene]:
        return list(self.db.scalars(
            select(Scene).where(Scene.document_id == document_id).order_by(asc(Scene.start_ms))))

    def subtitles_for(self, document_id: str) -> List[Subtitle]:
        return list(self.db.scalars(
            select(Subtitle).where(Subtitle.document_id == document_id).order_by(asc(Subtitle.start_ms))))

    def chunks_for(self, document_id: str, chunk_type: Optional[str] = None) -> List[MediaChunk]:
        stmt = select(MediaChunk).where(MediaChunk.document_id == document_id)
        if chunk_type:
            stmt = stmt.where(MediaChunk.chunk_type == chunk_type)
        return list(self.db.scalars(stmt.order_by(asc(MediaChunk.chunk_index))))

    def counts(self, document_id: str) -> Dict[str, int]:
        def c(model):
            return int(self.db.scalar(select(func.count()).select_from(model)
                                      .where(model.document_id == document_id)) or 0)
        return {"segments": c(TranscriptSegment), "speakers": c(Speaker), "scenes": c(Scene),
                "frames": c(MediaFrame), "subtitles": c(Subtitle), "chunks": c(MediaChunk)}

    def clear_job_assets(self, job_id: str, document_id: str) -> None:
        """Remove a job's temporal assets + chunks before a reprocess (OCR cache is KEPT)."""
        for model in (TranscriptSegment, Speaker, SpeakerTurn, MediaFrame, Scene, Subtitle, MediaChunk):
            self.db.execute(delete(model).where(model.job_id == job_id))
        self.db.commit()
