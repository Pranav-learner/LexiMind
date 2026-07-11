"""Multimodal ingestion data access — the ONLY place that issues SQL for ingestion tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import asc, delete, desc, func, select
from sqlalchemy.orm import Session

from app.ingestion.models import (
    ExtractedFigure,
    ExtractedImage,
    ExtractedTable,
    MultimodalChunk,
    OcrResult,
    ProcessingJob,
    ProcessingLog,
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class IngestionRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ jobs
    def get_job(self, job_id: str, owner_id: str) -> Optional[ProcessingJob]:
        return self.db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id, ProcessingJob.owner_id == owner_id))

    def get_job_by_id_only(self, job_id: str) -> Optional[ProcessingJob]:
        return self.db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id))

    def latest_job_for_document(self, document_id: str, owner_id: str) -> Optional[ProcessingJob]:
        return self.db.scalar(
            select(ProcessingJob).where(ProcessingJob.document_id == document_id, ProcessingJob.owner_id == owner_id)
            .order_by(desc(ProcessingJob.created_at)).limit(1)
        )

    def create_job(self, job: ProcessingJob) -> ProcessingJob:
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def save_job(self, job: ProcessingJob) -> ProcessingJob:
        job.updated_at = _now()
        self.db.commit()
        self.db.refresh(job)
        return job

    # ------------------------------------------------------------------ logs
    def log(self, job: ProcessingJob, stage: str, message: str, level: str = "info") -> None:
        self.db.add(ProcessingLog(job_id=job.id, workspace_id=job.workspace_id, stage=stage,
                                  level=level, message=message[:2000]))
        self.db.commit()

    def logs_for(self, job_id: str) -> List[ProcessingLog]:
        return list(self.db.scalars(
            select(ProcessingLog).where(ProcessingLog.job_id == job_id).order_by(asc(ProcessingLog.created_at))
        ))

    # ------------------------------------------------------------------ ocr cache
    def ocr_for_document(self, document_id: str) -> List[OcrResult]:
        return list(self.db.scalars(
            select(OcrResult).where(OcrResult.document_id == document_id).order_by(asc(OcrResult.page_number))
        ))

    def get_ocr(self, document_id: str, page_number: int, content_hash: str) -> Optional[OcrResult]:
        return self.db.scalar(select(OcrResult).where(
            OcrResult.document_id == document_id, OcrResult.page_number == page_number,
            OcrResult.content_hash == content_hash))

    def add_ocr(self, row: OcrResult) -> OcrResult:
        self.db.add(row)
        self.db.commit()
        return row

    # ------------------------------------------------------------------ assets
    def add_image(self, row: ExtractedImage) -> ExtractedImage:
        self.db.add(row); self.db.commit(); self.db.refresh(row); return row

    def add_table(self, row: ExtractedTable) -> ExtractedTable:
        self.db.add(row); self.db.commit(); self.db.refresh(row); return row

    def add_figure(self, row: ExtractedFigure) -> ExtractedFigure:
        self.db.add(row); self.db.commit(); self.db.refresh(row); return row

    def add_chunks(self, chunks: List[MultimodalChunk]) -> int:
        if chunks:
            self.db.add_all(chunks)
            self.db.commit()
        return len(chunks)

    def images_for(self, document_id: str) -> List[ExtractedImage]:
        return list(self.db.scalars(select(ExtractedImage).where(ExtractedImage.document_id == document_id).order_by(asc(ExtractedImage.page_number))))

    def tables_for(self, document_id: str) -> List[ExtractedTable]:
        return list(self.db.scalars(select(ExtractedTable).where(ExtractedTable.document_id == document_id).order_by(asc(ExtractedTable.page_number))))

    def figures_for(self, document_id: str) -> List[ExtractedFigure]:
        return list(self.db.scalars(select(ExtractedFigure).where(ExtractedFigure.document_id == document_id).order_by(asc(ExtractedFigure.page_number))))

    def chunks_for(self, document_id: str, chunk_type: Optional[str] = None) -> List[MultimodalChunk]:
        stmt = select(MultimodalChunk).where(MultimodalChunk.document_id == document_id)
        if chunk_type:
            stmt = stmt.where(MultimodalChunk.chunk_type == chunk_type)
        return list(self.db.scalars(stmt.order_by(asc(MultimodalChunk.chunk_index))))

    def counts(self, document_id: str) -> Dict[str, int]:
        def c(model):
            return int(self.db.scalar(select(func.count()).select_from(model).where(model.document_id == document_id)) or 0)
        return {"images": c(ExtractedImage), "tables": c(ExtractedTable),
                "figures": c(ExtractedFigure), "chunks": c(MultimodalChunk)}

    def clear_job_assets(self, job_id: str, document_id: str) -> None:
        """Remove a job's extracted assets + chunks before a reprocess (OCR cache is KEPT)."""
        self.db.execute(delete(ExtractedImage).where(ExtractedImage.job_id == job_id))
        self.db.execute(delete(ExtractedTable).where(ExtractedTable.job_id == job_id))
        self.db.execute(delete(ExtractedFigure).where(ExtractedFigure.job_id == job_id))
        self.db.execute(delete(MultimodalChunk).where(MultimodalChunk.job_id == job_id))
        self.db.commit()
