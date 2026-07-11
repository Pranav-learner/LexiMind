"""Citation-intelligence data access — reads over the derived index tables.

Workspace-scoped. All writes to the index happen in `indexer.py`; this repository only queries
`Citation` / `CitationReference` / `KnowledgeReference` for the panel, explorer, search, and stats.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.citations.models import Citation, CitationReference, KnowledgeReference
from app.citations.schemas import CitationSortField, ReferenceType, SortOrder


class CitationRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ citations
    def get(self, citation_id: str, workspace_id: str) -> Optional[Citation]:
        return self.db.scalar(
            select(Citation).where(Citation.id == citation_id, Citation.workspace_id == workspace_id)
        )

    def get_by_chunk(self, workspace_id: str, document_id: Optional[str], chunk_id: Optional[str]) -> Optional[Citation]:
        stmt = select(Citation).where(Citation.workspace_id == workspace_id)
        if chunk_id:
            stmt = stmt.where(Citation.chunk_id == chunk_id)
        elif document_id:
            stmt = stmt.where(Citation.document_id == document_id)
        else:
            return None
        return self.db.scalar(stmt.limit(1))

    def search(
        self, workspace_id: str, *, page: int = 1, page_size: int = 20,
        keyword: Optional[str] = None, document_id: Optional[str] = None,
        page_number: Optional[int] = None, reference_type: Optional[ReferenceType] = None,
        min_confidence: Optional[float] = None,
        sort_by: CitationSortField = CitationSortField.reference_count, order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Citation], int]:
        conds = [Citation.workspace_id == workspace_id]
        if keyword:
            conds.append(func.lower(Citation.citation_text).like(f"%{keyword.strip().lower()}%"))
        if document_id:
            conds.append(Citation.document_id == document_id)
        if page_number is not None:
            conds.append(Citation.page_number == page_number)
        if min_confidence is not None:
            conds.append(Citation.confidence >= min_confidence)
        if reference_type is not None:
            sub = select(CitationReference.citation_id).where(
                CitationReference.workspace_id == workspace_id,
                CitationReference.reference_type == reference_type.value,
            )
            conds.append(Citation.id.in_(sub))

        total = self.db.scalar(select(func.count()).select_from(Citation).where(*conds)) or 0
        column = getattr(Citation, sort_by.value)
        direction = desc if order == SortOrder.desc else asc
        stmt = (select(Citation).where(*conds)
                .order_by(direction(column), desc(Citation.id))
                .offset(max(0, page - 1) * page_size).limit(page_size))
        return list(self.db.scalars(stmt)), int(total)

    # ------------------------------------------------------------------ references
    def references_for(self, citation_id: str) -> List[CitationReference]:
        return list(self.db.scalars(
            select(CitationReference).where(CitationReference.citation_id == citation_id)
            .order_by(asc(CitationReference.reference_type))
        ))

    def reference_type_counts(self, citation_id: str) -> Dict[str, int]:
        rows = self.db.execute(
            select(CitationReference.reference_type, func.count())
            .where(CitationReference.citation_id == citation_id)
            .group_by(CitationReference.reference_type)
        ).all()
        return {t: int(n) for t, n in rows}

    # ------------------------------------------------------------------ knowledge
    def knowledge_for(self, citation_id: str) -> List[Tuple[KnowledgeReference, Optional[Citation]]]:
        """Return each knowledge edge with its resolved neighbour citation (for text/page)."""
        rows = self.db.execute(
            select(KnowledgeReference, Citation)
            .outerjoin(Citation, Citation.id == KnowledgeReference.related_citation_id)
            .where(KnowledgeReference.citation_id == citation_id)
            .order_by(desc(KnowledgeReference.strength))
        ).all()
        return [(k, c) for k, c in rows]

    def same_document_citations(self, workspace_id: str, document_id: str, *, exclude_id: str, limit: int = 20) -> List[Citation]:
        return list(self.db.scalars(
            select(Citation).where(
                Citation.workspace_id == workspace_id, Citation.document_id == document_id,
                Citation.id != exclude_id,
            ).order_by(desc(Citation.reference_count)).limit(limit)
        ))

    def document_context(self, workspace_id: str, document_id: Optional[str]) -> Tuple[int, int]:
        if not document_id:
            return 0, 0
        cit_count = self.db.scalar(
            select(func.count()).select_from(Citation)
            .where(Citation.workspace_id == workspace_id, Citation.document_id == document_id)
        ) or 0
        ref_count = self.db.scalar(
            select(func.coalesce(func.sum(Citation.reference_count), 0))
            .where(Citation.workspace_id == workspace_id, Citation.document_id == document_id)
        ) or 0
        return int(cit_count), int(ref_count)

    # ------------------------------------------------------------------ stats
    def stats(self, workspace_id: str) -> Dict:
        total_citations = self.db.scalar(
            select(func.count()).select_from(Citation).where(Citation.workspace_id == workspace_id)
        ) or 0
        total_references = self.db.scalar(
            select(func.count()).select_from(CitationReference).where(CitationReference.workspace_id == workspace_id)
        ) or 0
        documents_cited = self.db.scalar(
            select(func.count(func.distinct(Citation.document_id)))
            .where(Citation.workspace_id == workspace_id, Citation.document_id.is_not(None))
        ) or 0
        avg_conf = self.db.scalar(
            select(func.coalesce(func.avg(Citation.confidence), 0.0))
            .where(Citation.workspace_id == workspace_id, Citation.confidence.is_not(None))
        ) or 0.0
        high_conf = self.db.scalar(
            select(func.count()).select_from(Citation)
            .where(Citation.workspace_id == workspace_id, Citation.confidence >= 0.7)
        ) or 0
        by_type_rows = self.db.execute(
            select(CitationReference.reference_type, func.count())
            .where(CitationReference.workspace_id == workspace_id)
            .group_by(CitationReference.reference_type)
        ).all()
        by_type = {"message": 0, "summary": 0, "note": 0, "flashcard": 0}
        for t, n in by_type_rows:
            by_type[t] = int(n)
        most = list(self.db.scalars(
            select(Citation).where(Citation.workspace_id == workspace_id)
            .order_by(desc(Citation.reference_count), desc(Citation.confidence)).limit(5)
        ))
        return {
            "total_citations": int(total_citations), "total_references": int(total_references),
            "documents_cited": int(documents_cited), "avg_confidence": round(float(avg_conf), 4),
            "high_confidence": int(high_conf), "references_by_type": by_type, "most_referenced": most,
        }
