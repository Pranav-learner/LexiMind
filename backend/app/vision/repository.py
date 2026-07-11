"""Vision Intelligence data access — the ONLY place that issues SQL for vision tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import asc, delete, desc, func, or_, select
from sqlalchemy.orm import Session

from app.vision.models import VisionAnalysis, VisionEmbedding, VisionJob


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VisionRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ jobs
    def get_job(self, job_id: str, owner_id: str) -> Optional[VisionJob]:
        return self.db.scalar(select(VisionJob).where(VisionJob.id == job_id, VisionJob.owner_id == owner_id))

    def get_job_by_id_only(self, job_id: str) -> Optional[VisionJob]:
        return self.db.scalar(select(VisionJob).where(VisionJob.id == job_id))

    def latest_job_for_document(self, document_id: str, owner_id: str) -> Optional[VisionJob]:
        return self.db.scalar(
            select(VisionJob).where(VisionJob.document_id == document_id, VisionJob.owner_id == owner_id)
            .order_by(desc(VisionJob.created_at)).limit(1))

    def create_job(self, job: VisionJob) -> VisionJob:
        self.db.add(job); self.db.commit(); self.db.refresh(job); return job

    def save_job(self, job: VisionJob) -> VisionJob:
        job.updated_at = _now(); self.db.commit(); self.db.refresh(job); return job

    # ------------------------------------------------------------------ analyses
    def get_analysis(self, analysis_id: str, workspace_id: str) -> Optional[VisionAnalysis]:
        return self.db.scalar(select(VisionAnalysis).where(
            VisionAnalysis.id == analysis_id, VisionAnalysis.workspace_id == workspace_id))

    def analysis_for_asset(self, asset_type: str, asset_id: str) -> Optional[VisionAnalysis]:
        return self.db.scalar(select(VisionAnalysis).where(
            VisionAnalysis.asset_type == asset_type, VisionAnalysis.asset_id == asset_id))

    def analyses_for_document(self, document_id: str, image_type: Optional[str] = None) -> List[VisionAnalysis]:
        stmt = select(VisionAnalysis).where(VisionAnalysis.document_id == document_id)
        if image_type:
            stmt = stmt.where(VisionAnalysis.image_type == image_type)
        return list(self.db.scalars(stmt.order_by(asc(VisionAnalysis.page_number))))

    def upsert_analysis(self, row: VisionAnalysis) -> VisionAnalysis:
        existing = self.analysis_for_asset(row.asset_type, row.asset_id)
        if existing is not None:
            self.db.delete(existing)
            self.db.flush()
        self.db.add(row); self.db.commit(); self.db.refresh(row); return row

    def clear_job(self, job_id: str) -> None:
        ids = list(self.db.scalars(select(VisionAnalysis.id).where(VisionAnalysis.job_id == job_id)))
        if ids:
            self.db.execute(delete(VisionEmbedding).where(VisionEmbedding.analysis_id.in_(ids)))
        self.db.execute(delete(VisionAnalysis).where(VisionAnalysis.job_id == job_id))
        self.db.commit()

    # ------------------------------------------------------------------ embeddings
    def add_embedding(self, row: VisionEmbedding) -> VisionEmbedding:
        existing = self.db.scalar(select(VisionEmbedding).where(
            VisionEmbedding.asset_type == row.asset_type, VisionEmbedding.asset_id == row.asset_id,
            VisionEmbedding.model == row.model))
        if existing is not None:
            self.db.delete(existing); self.db.flush()
        self.db.add(row); self.db.commit(); self.db.refresh(row); return row

    def embedding_for_analysis(self, analysis_id: str) -> Optional[VisionEmbedding]:
        return self.db.scalar(select(VisionEmbedding).where(VisionEmbedding.analysis_id == analysis_id).limit(1))

    def has_embedding(self, analysis_id: str) -> bool:
        return self.embedding_for_analysis(analysis_id) is not None

    # ------------------------------------------------------------------ search index
    def search_meta(self, workspace_id: str, *, keyword: Optional[str] = None,
                    image_type: Optional[str] = None, limit: int = 100) -> List[VisionAnalysis]:
        conds = [VisionAnalysis.workspace_id == workspace_id]
        if image_type:
            conds.append(VisionAnalysis.image_type == image_type)
        if keyword:
            conds.append(func.lower(VisionAnalysis.caption).like(f"%{keyword.strip().lower()}%"))
        return list(self.db.scalars(
            select(VisionAnalysis).where(*conds).order_by(desc(VisionAnalysis.created_at)).limit(limit)))
