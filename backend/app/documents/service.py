"""Document business logic — the single place lifecycle rules live.

Depends on a `DocumentRepository` (data) and the pure `validation` helpers, and optionally a
`WorkspaceService` so it can keep the workspace's denormalized `document_count` accurate. It
owns the rules the API and any future caller must not bypass:
- display-name / description validation + normalization,
- duplicate-file prevention (case-insensitive, per workspace, among live rows),
- the processing lifecycle (uploaded → … → ready / failed) and its progress,
- archive/restore state transitions,
- soft-delete by default, hard-delete only on explicit request.

Cross-store chunk cleanup (FAISS/BM25) is NOT done here — that needs the vector singletons and
is orchestrated by the API route via `app.documents.indexing`, keeping this layer faiss-free
and unit-testable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from app.documents import validation
from app.documents.errors import (
    DocumentNotFound,
    DocumentStateError,
    DuplicateDocument,
)
from app.documents.models import Document
from app.documents.repository import DocumentRepository
from app.documents.schemas import (
    PROCESSING_STAGES,
    ArchivedFilter,
    IndexedFilter,
    ProcessingStatus,
    SortField,
    SortOrder,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentService:
    def __init__(self, repo: DocumentRepository, workspace_service=None):
        self.repo = repo
        # Optional: when present, ingestion/deletion keep workspace.document_count in sync.
        self.workspace_service = workspace_service

    # ------------------------------------------------------------------ helpers
    def _get_or_404(self, document_id: str, owner_id: str) -> Document:
        doc = self.repo.get(document_id, owner_id)
        if doc is None:
            raise DocumentNotFound(document_id)
        return doc

    def _ensure_filename_free(
        self, workspace_id: str, filename: str, *, exclude_id: Optional[str] = None
    ) -> None:
        cf = validation.normalize_name_for_compare(filename)
        if self.repo.filename_exists(workspace_id, cf, exclude_id=exclude_id):
            raise DuplicateDocument(filename)

    def _adjust_ws_counter(self, workspace_id: str, owner_id: str, delta: int) -> None:
        """Best-effort workspace counter maintenance (drift is non-fatal, never blocks a doc op)."""
        if self.workspace_service is None:
            return
        try:
            self.workspace_service.adjust_counter(workspace_id, owner_id, "document_count", delta)
        except Exception:
            pass

    # ------------------------------------------------------------------ lifecycle: create
    def create_pending(
        self,
        owner_id: str,
        workspace_id: str,
        *,
        filename: str,
        vector_document_id: str,
        storage_path: str,
        file_type: str,
        mime_type: str,
        file_size: int,
        display_name: Optional[str] = None,
        description: str = "",
        media_type: str = "document",
    ) -> Document:
        """Create the row for a freshly-uploaded file, before processing runs.

        Duplicate/validation errors are raised here so the caller can reject the upload before
        doing any expensive extraction/embedding work.
        """
        display = validation.validate_display_name(display_name, fallback=filename)
        description = validation.validate_description(description)
        self._ensure_filename_free(workspace_id, filename)

        doc = Document(
            owner_id=owner_id,
            workspace_id=workspace_id,
            vector_document_id=vector_document_id,
            filename=filename,
            display_name=display,
            description=description,
            media_type=media_type,
            file_type=file_type,
            mime_type=mime_type,
            file_size=file_size,
            storage_path=storage_path,
            processing_status=ProcessingStatus.processing.value,
            processing_stage=PROCESSING_STAGES[0],  # "uploaded"
            indexing_status="pending",
            upload_progress=0,
        )
        return self.repo.create(doc)

    def set_stage(self, document: Document, stage: str) -> Document:
        """Advance the processing stage and derive an upload_progress percentage from it."""
        if stage in PROCESSING_STAGES:
            idx = PROCESSING_STAGES.index(stage)
            document.upload_progress = round(idx / (len(PROCESSING_STAGES) - 1) * 100)
        document.processing_stage = stage
        if stage == "ready":
            document.processing_status = ProcessingStatus.ready.value
        return self.repo.save(document)

    def complete(
        self,
        document: Document,
        *,
        page_count: int,
        word_count: int,
        chunk_count: int,
        language: str,
        embedding_model: str,
        embedding_dimension: int,
        processing_ms: int,
        count_as_new: bool = True,
    ) -> Document:
        """Mark processing successful and record the derived statistics.

        `count_as_new` bumps the workspace document_count — True on first upload, False on a
        re-index of an already-counted document.
        """
        document.page_count = page_count
        document.word_count = word_count
        document.chunk_count = chunk_count
        document.language = language
        document.embedding_model = embedding_model
        document.embedding_dimension = embedding_dimension
        document.processing_ms = processing_ms
        document.processing_status = ProcessingStatus.ready.value
        document.processing_stage = "ready"
        document.upload_progress = 100
        document.indexing_status = "indexed"
        document.processing_error = None
        document.last_indexed_at = _now()
        saved = self.repo.save(document)
        if count_as_new:
            self._adjust_ws_counter(document.workspace_id, document.owner_id, +1)
        return saved

    def fail(self, document: Document, error: str) -> Document:
        document.processing_status = ProcessingStatus.failed.value
        document.indexing_status = "failed"
        document.processing_error = (error or "Processing failed.")[:4000]
        return self.repo.save(document)

    # ------------------------------------------------------------------ commands
    def update(
        self,
        document_id: str,
        owner_id: str,
        *,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Document:
        """Rename (display name) and/or edit description. Physical file is never renamed."""
        doc = self._get_or_404(document_id, owner_id)
        if display_name is not None:
            doc.display_name = validation.validate_display_name(display_name, fallback=doc.filename)
        if description is not None:
            doc.description = validation.validate_description(description)
        return self.repo.save(doc)

    def archive(self, document_id: str, owner_id: str) -> Document:
        doc = self._get_or_404(document_id, owner_id)
        if doc.is_archived:
            raise DocumentStateError("Document is already archived.")
        doc.is_archived = True
        return self.repo.save(doc)

    def restore(self, document_id: str, owner_id: str) -> Document:
        doc = self._get_or_404(document_id, owner_id)
        if not doc.is_archived:
            raise DocumentStateError("Document is not archived.")
        doc.is_archived = False
        return self.repo.save(doc)

    def delete(self, document_id: str, owner_id: str, *, permanent: bool = False) -> Document:
        """Soft-delete by default; hard-delete only when explicitly requested.

        Returns the (now-deleted) document so the caller can perform cross-store cleanup
        (chunks, physical file) for a permanent delete. Decrements the workspace document_count
        exactly once for a document that had been counted (i.e. reached `ready`).
        """
        doc = self._get_or_404(document_id, owner_id)
        was_counted = doc.processing_status == ProcessingStatus.ready.value
        if permanent:
            self.repo.hard_delete(doc)
        else:
            self.repo.soft_delete(doc)
        if was_counted:
            self._adjust_ws_counter(doc.workspace_id, doc.owner_id, -1)
        return doc

    def mark_stale(self, document: Document) -> Document:
        """Flag that a document's index is out of date (used before a re-index)."""
        document.indexing_status = "stale"
        return self.repo.save(document)

    # ------------------------------------------------------------------ queries
    def get(self, document_id: str, owner_id: str) -> Document:
        return self._get_or_404(document_id, owner_id)

    def get_by_vector_id(self, workspace_id: str, vector_document_id: str) -> Optional[Document]:
        """Context-Engine accessor: rich metadata for a retrieved chunk's document."""
        return self.repo.get_by_vector_id(workspace_id, vector_document_id)

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
        page = max(1, page)
        page_size = min(max(1, page_size), 100)  # hard cap protects against huge pages
        return self.repo.list(
            owner_id,
            workspace_id,
            page=page,
            page_size=page_size,
            search=search,
            archived=archived,
            indexed=indexed,
            file_type=file_type,
            language=language,
            sort_by=sort_by,
            order=order,
        )
