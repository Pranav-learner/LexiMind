"""Unit tests for DocumentRepository (SQL layer) against in-memory SQLite."""

from __future__ import annotations

from app.documents.models import Document
from app.documents.repository import DocumentRepository
from app.documents.schemas import ArchivedFilter, IndexedFilter, SortField, SortOrder

OWNER = "user_1"
WS = "ws_1"


def _doc(repo, *, filename, display=None, description="", file_type="pdf", language="en",
         indexing_status="indexed", archived=False, workspace_id=WS, owner_id=OWNER,
         vector_document_id=None, file_size=100, page_count=1):
    d = Document(
        owner_id=owner_id,
        workspace_id=workspace_id,
        vector_document_id=vector_document_id or f"doc_{filename}",
        filename=filename,
        display_name=display or filename,
        description=description,
        file_type=file_type,
        language=language,
        indexing_status=indexing_status,
        is_archived=archived,
        file_size=file_size,
        page_count=page_count,
        processing_status="ready",
    )
    return repo.create(d)


def test_get_is_owner_scoped(db_session):
    repo = DocumentRepository(db_session)
    d = _doc(repo, filename="a.pdf")
    assert repo.get(d.id, OWNER) is not None
    assert repo.get(d.id, "user_other") is None


def test_filename_exists_case_insensitive_live_only(db_session):
    repo = DocumentRepository(db_session)
    d = _doc(repo, filename="Notes.pdf")
    assert repo.filename_exists(WS, "notes.pdf") is True
    assert repo.filename_exists(WS, "notes.pdf", exclude_id=d.id) is False
    repo.soft_delete(d)
    assert repo.filename_exists(WS, "notes.pdf") is False  # freed after soft delete


def test_soft_delete_hides_from_list(db_session):
    repo = DocumentRepository(db_session)
    d = _doc(repo, filename="a.pdf")
    _doc(repo, filename="b.pdf")
    repo.soft_delete(d)
    items, total = repo.list(OWNER, WS)
    assert total == 1
    assert {i.filename for i in items} == {"b.pdf"}


def test_list_pagination_and_total(db_session):
    repo = DocumentRepository(db_session)
    for i in range(5):
        _doc(repo, filename=f"f{i}.pdf")
    items, total = repo.list(OWNER, WS, page=1, page_size=2)
    assert total == 5 and len(items) == 2
    items2, _ = repo.list(OWNER, WS, page=3, page_size=2)
    assert len(items2) == 1


def test_list_search_matches_filename_display_description(db_session):
    repo = DocumentRepository(db_session)
    _doc(repo, filename="alpha.pdf", display="Alpha Report", description="quarterly numbers")
    _doc(repo, filename="beta.pdf", display="Beta", description="nothing special")
    assert repo.list(OWNER, WS, search="alpha")[1] == 1
    assert repo.list(OWNER, WS, search="quarterly")[1] == 1
    assert repo.list(OWNER, WS, search="Beta")[1] == 1
    assert repo.list(OWNER, WS, search="zzz")[1] == 0


def test_list_filters_archived_indexed_type_language(db_session):
    repo = DocumentRepository(db_session)
    _doc(repo, filename="a.pdf", archived=False, indexing_status="indexed", language="en")
    _doc(repo, filename="b.pdf", archived=True, indexing_status="pending", language="unknown")

    assert repo.list(OWNER, WS, archived=ArchivedFilter.active)[1] == 1
    assert repo.list(OWNER, WS, archived=ArchivedFilter.archived)[1] == 1
    assert repo.list(OWNER, WS, archived=ArchivedFilter.all)[1] == 2
    assert repo.list(OWNER, WS, archived=ArchivedFilter.all, indexed=IndexedFilter.indexed)[1] == 1
    assert repo.list(OWNER, WS, archived=ArchivedFilter.all, indexed=IndexedFilter.unindexed)[1] == 1
    assert repo.list(OWNER, WS, archived=ArchivedFilter.all, language="en")[1] == 1


def test_list_sorting(db_session):
    repo = DocumentRepository(db_session)
    _doc(repo, filename="a.pdf", display="Zebra", file_size=10)
    _doc(repo, filename="b.pdf", display="Apple", file_size=99)
    items, _ = repo.list(OWNER, WS, sort_by=SortField.display_name, order=SortOrder.asc)
    assert [i.display_name for i in items] == ["Apple", "Zebra"]
    items, _ = repo.list(OWNER, WS, sort_by=SortField.file_size, order=SortOrder.desc)
    assert [i.file_size for i in items] == [99, 10]


def test_excluded_vector_ids_covers_archived_and_deleted(db_session):
    repo = DocumentRepository(db_session)
    _doc(repo, filename="live.pdf", vector_document_id="doc_live", archived=False)
    _doc(repo, filename="arch.pdf", vector_document_id="doc_arch", archived=True)
    gone = _doc(repo, filename="gone.pdf", vector_document_id="doc_gone")
    repo.soft_delete(gone)
    excluded = set(repo.list_excluded_vector_ids(WS))
    assert excluded == {"doc_arch", "doc_gone"}


def test_get_by_vector_id(db_session):
    repo = DocumentRepository(db_session)
    _doc(repo, filename="a.pdf", vector_document_id="doc_xyz")
    assert repo.get_by_vector_id(WS, "doc_xyz").filename == "a.pdf"
    assert repo.get_by_vector_id(WS, "missing") is None
