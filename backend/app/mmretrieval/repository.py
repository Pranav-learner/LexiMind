"""Multimodal retrieval data access — reads the unified stores Modules 1–2 populated.

No new retrieval storage: this reads `MultimodalChunk` (text/OCR unified chunks), `VisionAnalysis`
(image/diagram/table understanding), `ExtractedTable` (structured tables), and `Document` (metadata).
Also owns the `RetrievalLog` writes + stats aggregation. Nothing here touches the FAISS text index.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.mmretrieval.models import RetrievalLog


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RetrievalRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ candidate reads
    def chunks(self, workspace_id: str, chunk_types: List[str], document_id: Optional[str] = None, limit: int = 500):
        from app.ingestion.models import MultimodalChunk
        stmt = select(MultimodalChunk).where(
            MultimodalChunk.workspace_id == workspace_id, MultimodalChunk.chunk_type.in_(chunk_types))
        if document_id:
            stmt = stmt.where(MultimodalChunk.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def vision(self, workspace_id: str, image_types: Optional[List[str]] = None,
               exclude_types: Optional[List[str]] = None, document_id: Optional[str] = None, limit: int = 500):
        from app.vision.models import VisionAnalysis
        stmt = select(VisionAnalysis).where(VisionAnalysis.workspace_id == workspace_id)
        if image_types:
            stmt = stmt.where(VisionAnalysis.image_type.in_(image_types))
        if exclude_types:
            stmt = stmt.where(VisionAnalysis.image_type.notin_(exclude_types))
        if document_id:
            stmt = stmt.where(VisionAnalysis.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def tables(self, workspace_id: str, document_id: Optional[str] = None, limit: int = 500):
        from app.ingestion.models import ExtractedTable
        stmt = select(ExtractedTable).where(ExtractedTable.workspace_id == workspace_id)
        if document_id:
            stmt = stmt.where(ExtractedTable.document_id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    def documents(self, workspace_id: str, owner_id: str, document_id: Optional[str] = None, limit: int = 500):
        from app.documents.models import Document
        stmt = select(Document).where(Document.workspace_id == workspace_id, Document.owner_id == owner_id,
                                      Document.deleted_at.is_(None))
        if document_id:
            stmt = stmt.where(Document.id == document_id)
        return list(self.db.scalars(stmt.limit(limit)))

    # ------------------------------------------------------------------ counts (stats / health)
    def indexed_counts(self, workspace_id: str) -> Dict[str, int]:
        from app.documents.models import Document
        from app.ingestion.models import MultimodalChunk
        from app.vision.models import VisionAnalysis, VisionEmbedding

        def c(model, *conds):
            return int(self.db.scalar(select(func.count()).select_from(model).where(*conds)) or 0)
        return {
            "text_chunks": c(MultimodalChunk, MultimodalChunk.workspace_id == workspace_id, MultimodalChunk.chunk_type == "text"),
            "ocr_chunks": c(MultimodalChunk, MultimodalChunk.workspace_id == workspace_id, MultimodalChunk.chunk_type == "ocr"),
            "vision_assets": c(VisionAnalysis, VisionAnalysis.workspace_id == workspace_id),
            "vision_embeddings": c(VisionEmbedding, VisionEmbedding.workspace_id == workspace_id),
            "documents": c(Document, Document.workspace_id == workspace_id, Document.deleted_at.is_(None)),
        }

    def embedding_queue(self, workspace_id: str) -> Dict[str, int]:
        from app.ingestion.models import MultimodalChunk
        def c(*conds):
            return int(self.db.scalar(select(func.count()).select_from(MultimodalChunk).where(*conds)) or 0)
        return {
            "pending": c(MultimodalChunk.workspace_id == workspace_id, MultimodalChunk.embedding_status == "pending"),
            "embedded": c(MultimodalChunk.workspace_id == workspace_id, MultimodalChunk.embedding_status == "embedded"),
        }

    # ------------------------------------------------------------------ retrieval log / stats
    def log_search(self, log: RetrievalLog) -> None:
        self.db.add(log)
        self.db.commit()

    def stats(self, workspace_id: str, *, limit_recent: int = 10) -> Dict:
        total = int(self.db.scalar(select(func.count()).select_from(RetrievalLog).where(RetrievalLog.workspace_id == workspace_id)) or 0)
        avg = float(self.db.scalar(select(func.coalesce(func.avg(RetrievalLog.total_ms), 0.0)).where(RetrievalLog.workspace_id == workspace_id)) or 0.0)
        rows = list(self.db.scalars(select(RetrievalLog).where(RetrievalLog.workspace_id == workspace_id).order_by(desc(RetrievalLog.created_at)).limit(200)))
        usage: Dict[str, int] = {}
        for r in rows:
            for m in (r.intents or []):
                usage[m] = usage.get(m, 0) + 1
        recent = [r.query for r in rows[:limit_recent]]
        return {"searches": total, "avg_latency_ms": round(avg, 2), "modality_usage": usage, "recent_queries": recent}
