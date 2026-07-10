"""Document data-access layer. The ONLY place that issues SQL for documents.

Every query is scoped to `owner_id` + `workspace_id` and, unless explicitly stated, excludes
soft-deleted rows (`deleted_at IS NULL`). Listing is done in two cheap queries (count + a
windowed select) with SQL-side pagination, sorting, search, and filtering — no N+1, no
in-memory table scans.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.documents.models import Document
from app.documents.schemas import (
    ArchivedFilter,
    IndexedFilter,
    SortField,
    SortOrder,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ reads
    def get(
        self,
        document_id: str,
        owner_id: str,
        *,
        include_deleted: bool = False,
    ) -> Optional[Document]:
        stmt = select(Document).where(
            Document.id == document_id, Document.owner_id == owner_id
        )
        if not include_deleted:
            stmt = stmt.where(Document.deleted_at.is_(None))
        return self.db.scalar(stmt)

    def get_by_vector_id(
        self, workspace_id: str, vector_document_id: str
    ) -> Optional[Document]:
        """Resolve the Document row backing a retrieved chunk's `document_id`.

        This is the Context-Engine integration point (Phase 2): given a chunk's
        `metadata["document_id"]` + workspace, callers get the rich document metadata
        (display_name, description, page/word counts, language) for smarter context
        assembly and citation generation. Live rows only.
        """
        stmt = (
            select(Document)
            .where(
                Document.workspace_id == workspace_id,
                Document.vector_document_id == vector_document_id,
                Document.deleted_at.is_(None),
            )
            .limit(1)
        )
        return self.db.scalar(stmt)

    def filename_exists(
        self,
        workspace_id: str,
        filename_cf: str,
        *,
        exclude_id: Optional[str] = None,
    ) -> bool:
        """Case-insensitive duplicate-file check among a workspace's live rows."""
        stmt = select(Document.id).where(
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
            func.lower(Document.filename) == filename_cf,
        )
        if exclude_id:
            stmt = stmt.where(Document.id != exclude_id)
        return self.db.scalar(stmt) is not None

    def list(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        archived: ArchivedFilter = ArchivedFilter.active,
        indexed: IndexedFilter = IndexedFilter.any,
        file_type: Optional[str] = None,
        language: Optional[str] = None,
        sort_by: SortField = SortField.created_at,
        order: SortOrder = SortOrder.desc,
    ) -> Tuple[List[Document], int]:
        """Return (page_items, total_count). Search matches filename OR display_name OR description."""
        conditions = [
            Document.owner_id == owner_id,
            Document.workspace_id == workspace_id,
            Document.deleted_at.is_(None),
        ]
        if archived == ArchivedFilter.active:
            conditions.append(Document.is_archived.is_(False))
        elif archived == ArchivedFilter.archived:
            conditions.append(Document.is_archived.is_(True))

        if indexed == IndexedFilter.indexed:
            conditions.append(Document.indexing_status == "indexed")
        elif indexed == IndexedFilter.unindexed:
            conditions.append(Document.indexing_status != "indexed")

        if file_type:
            conditions.append(func.lower(Document.file_type) == file_type.strip().lower())
        if language:
            conditions.append(func.lower(Document.language) == language.strip().lower())

        if search:
            like = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(Document.filename).like(like),
                    func.lower(Document.display_name).like(like),
                    func.lower(Document.description).like(like),
                )
            )

        total = self.db.scalar(select(func.count()).select_from(Document).where(*conditions)) or 0

        column = getattr(Document, sort_by.value)
        direction = desc if order == SortOrder.desc else asc
        stmt = (
            select(Document)
            .where(*conditions)
            .order_by(direction(column), desc(Document.id))  # id tiebreak = stable paging
            .offset(max(0, (page - 1)) * page_size)
            .limit(page_size)
        )
        return list(self.db.scalars(stmt)), int(total)

    def list_excluded_vector_ids(self, workspace_id: str) -> List[str]:
        """vector_document_ids that must NOT appear in normal retrieval for this workspace.

        That is any document which is archived OR soft-deleted. Used by the query route to
        exclude them without mutating the vector store (a cheap, indexed lookup). Distinct so
        a re-uploaded filename (shared derived id) yields one entry.
        """
        from sqlalchemy import or_

        stmt = (
            select(Document.vector_document_id)
            .where(
                Document.workspace_id == workspace_id,
                or_(Document.is_archived.is_(True), Document.deleted_at.is_not(None)),
            )
            .distinct()
        )
        return [row for row in self.db.scalars(stmt)]

    # ------------------------------------------------------------------ writes
    def create(self, document: Document) -> Document:
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def save(self, document: Document) -> Document:
        document.updated_at = _now()
        self.db.commit()
        self.db.refresh(document)
        return document

    def soft_delete(self, document: Document) -> None:
        document.deleted_at = _now()
        self.db.commit()

    def hard_delete(self, document: Document) -> None:
        self.db.delete(document)
        self.db.commit()
