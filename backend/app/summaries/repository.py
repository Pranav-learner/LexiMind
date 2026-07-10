"""Summary data-access layer. The ONLY place that issues SQL for summaries.

Owner + workspace scoped, soft-delete aware. Section/citation reads are batched to avoid N+1.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.summaries.models import Summary, SummaryCitation, SummarySection
from app.summaries.schemas import SortField, SortOrder, StatusFilter


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SummaryRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ reads
    def get(self, summary_id: str, owner_id: str, *, include_deleted: bool = False) -> Optional[Summary]:
        stmt = select(Summary).where(Summary.id == summary_id, Summary.owner_id == owner_id)
        if not include_deleted:
            stmt = stmt.where(Summary.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def get_by_id_only(self, summary_id: str) -> Optional[Summary]:
        """Lookup by id without an owner (used by the background runner's own session)."""
        return self.db.scalar(select(Summary).where(Summary.id == summary_id))

    def list(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        summary_type: Optional[str] = None,
        status: StatusFilter = StatusFilter.any,
        document_id: Optional[str] = None,
        sort_by: SortField = SortField.created_at,
        order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Summary], int]:
        conds = [
            Summary.owner_id == owner_id,
            Summary.workspace_id == workspace_id,
            Summary.deleted_at.is_(None),
        ]
        if summary_type:
            conds.append(Summary.summary_type == summary_type)
        if status != StatusFilter.any:
            conds.append(Summary.status == status.value)
        if document_id:
            conds.append(Summary.document_id == document_id)
        if search:
            like = f"%{search.strip().lower()}%"
            conds.append(func.lower(Summary.title).like(like))

        total = self.db.scalar(select(func.count()).select_from(Summary).where(*conds)) or 0
        column = getattr(Summary, sort_by.value)
        direction = desc if order == SortOrder.desc else asc
        stmt = (
            select(Summary)
            .where(*conds)
            .order_by(direction(column), desc(Summary.id))
            .offset(max(0, (page - 1)) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), int(total)

    def sections(self, summary_id: str) -> List[SummarySection]:
        return list(self.db.scalars(
            select(SummarySection).where(SummarySection.summary_id == summary_id).order_by(asc(SummarySection.order))
        ))

    def citations_for(self, section_ids: List[str]) -> Dict[str, List[SummaryCitation]]:
        if not section_ids:
            return {}
        grouped: Dict[str, List[SummaryCitation]] = defaultdict(list)
        for c in self.db.scalars(select(SummaryCitation).where(SummaryCitation.summary_section_id.in_(section_ids))):
            grouped[c.summary_section_id].append(c)
        return grouped

    # ------------------------------------------------------------------ writes
    def create(self, summary: Summary) -> Summary:
        self.db.add(summary)
        self.db.commit()
        self.db.refresh(summary)
        return summary

    def save(self, summary: Summary) -> Summary:
        summary.updated_at = _now()
        self.db.commit()
        self.db.refresh(summary)
        return summary

    def add_section(self, section: SummarySection, citations: List[SummaryCitation]) -> SummarySection:
        """Persist a section and its citations, linking each citation to the section's id.

        Flushes the section first so its generated id exists, then stamps it onto every citation
        (callers need not set `summary_section_id`).
        """
        self.db.add(section)
        self.db.flush()  # assigns section.id
        for c in citations:
            c.summary_section_id = section.id
        if citations:
            self.db.add_all(citations)
        self.db.commit()
        self.db.refresh(section)
        return section

    def clear_sections(self, summary_id: str) -> None:
        """Remove all sections + their citations (used before a regenerate)."""
        sec_ids = list(self.db.scalars(select(SummarySection.id).where(SummarySection.summary_id == summary_id)))
        if sec_ids:
            self.db.query(SummaryCitation).filter(SummaryCitation.summary_section_id.in_(sec_ids)).delete(
                synchronize_session=False
            )
            self.db.query(SummarySection).filter(SummarySection.summary_id == summary_id).delete(
                synchronize_session=False
            )
            self.db.commit()

    def soft_delete(self, summary: Summary) -> None:
        summary.deleted_at = _now()
        self.db.commit()

    def hard_delete(self, summary: Summary) -> None:
        self.clear_sections(summary.id)
        self.db.delete(summary)
        self.db.commit()
