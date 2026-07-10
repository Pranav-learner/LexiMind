"""Unit tests for DocumentService (business rules) against in-memory SQLite."""

from __future__ import annotations

import pytest

from app.documents.errors import (
    DocumentNotFound,
    DocumentStateError,
    DuplicateDocument,
)
from app.documents.repository import DocumentRepository
from app.documents.service import DocumentService

OWNER = "user_1"
WS = "ws_1"


class FakeWorkspaceService:
    def __init__(self):
        self.calls = []

    def adjust_counter(self, workspace_id, owner_id, field, delta):
        self.calls.append((field, delta))


def _service(db):
    ws = FakeWorkspaceService()
    return DocumentService(DocumentRepository(db), ws), ws


def _pending(service, filename="a.pdf", **kw):
    return service.create_pending(
        OWNER, WS,
        filename=filename,
        vector_document_id=f"doc_{filename}",
        storage_path=f"/tmp/{filename}",
        file_type="pdf",
        mime_type="application/pdf",
        file_size=100,
        **kw,
    )


def test_create_pending_defaults_and_state(db_session):
    service, _ = _service(db_session)
    doc = _pending(service)
    assert doc.display_name == "a.pdf"          # falls back to filename
    assert doc.processing_status == "processing"
    assert doc.processing_stage == "uploaded"
    assert doc.indexing_status == "pending"


def test_create_pending_duplicate_rejected(db_session):
    service, _ = _service(db_session)
    _pending(service, filename="dup.pdf")
    with pytest.raises(DuplicateDocument):
        _pending(service, filename="DUP.pdf")   # case-insensitive


def test_set_stage_progresses(db_session):
    service, _ = _service(db_session)
    doc = _pending(service)
    service.set_stage(doc, "embedding")
    assert 0 < doc.upload_progress < 100
    assert doc.processing_stage == "embedding"


def test_complete_sets_stats_and_bumps_counter_once(db_session):
    service, ws = _service(db_session)
    doc = _pending(service)
    service.complete(
        doc, page_count=3, word_count=120, chunk_count=7, language="en",
        embedding_model="all-MiniLM-L6-v2", embedding_dimension=384, processing_ms=42,
        count_as_new=True,
    )
    assert doc.processing_status == "ready"
    assert doc.indexing_status == "indexed"
    assert doc.upload_progress == 100
    assert doc.chunk_count == 7 and doc.page_count == 3 and doc.word_count == 120
    assert doc.last_indexed_at is not None
    assert ws.calls == [("document_count", 1)]


def test_reindex_completion_does_not_recount(db_session):
    service, ws = _service(db_session)
    doc = _pending(service)
    service.complete(doc, page_count=1, word_count=1, chunk_count=1, language="en",
                     embedding_model="m", embedding_dimension=384, processing_ms=1, count_as_new=True)
    service.complete(doc, page_count=1, word_count=1, chunk_count=2, language="en",
                     embedding_model="m", embedding_dimension=384, processing_ms=1, count_as_new=False)
    assert ws.calls == [("document_count", 1)]  # only the first upload counted


def test_fail_records_error(db_session):
    service, _ = _service(db_session)
    doc = _pending(service)
    service.fail(doc, "boom")
    assert doc.processing_status == "failed"
    assert doc.indexing_status == "failed"
    assert "boom" in doc.processing_error


def test_update_renames_display_name_only(db_session):
    service, _ = _service(db_session)
    doc = _pending(service, filename="orig.pdf")
    updated = service.update(doc.id, OWNER, display_name="Nice Title", description="desc")
    assert updated.display_name == "Nice Title"
    assert updated.description == "desc"
    assert updated.filename == "orig.pdf"       # physical filename untouched


def test_archive_restore_state_machine(db_session):
    service, _ = _service(db_session)
    doc = _pending(service)
    service.archive(doc.id, OWNER)
    assert doc.is_archived is True
    with pytest.raises(DocumentStateError):
        service.archive(doc.id, OWNER)          # already archived
    service.restore(doc.id, OWNER)
    assert doc.is_archived is False
    with pytest.raises(DocumentStateError):
        service.restore(doc.id, OWNER)          # not archived


def test_soft_delete_decrements_only_counted_docs(db_session):
    service, ws = _service(db_session)
    ready = _pending(service, filename="ready.pdf")
    service.complete(ready, page_count=1, word_count=1, chunk_count=1, language="en",
                     embedding_model="m", embedding_dimension=384, processing_ms=1)
    ws.calls.clear()
    service.delete(ready.id, OWNER, permanent=False)
    assert ws.calls == [("document_count", -1)]

    # A never-completed (failed/pending) doc was never counted → no decrement.
    pending = _pending(service, filename="pending.pdf")
    ws.calls.clear()
    service.delete(pending.id, OWNER, permanent=False)
    assert ws.calls == []


def test_delete_missing_raises(db_session):
    service, _ = _service(db_session)
    with pytest.raises(DocumentNotFound):
        service.delete("nope", OWNER)


def test_owner_scoping(db_session):
    service, _ = _service(db_session)
    doc = _pending(service)
    with pytest.raises(DocumentNotFound):
        service.get(doc.id, "user_other")
