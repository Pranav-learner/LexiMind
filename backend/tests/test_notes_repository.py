"""Unit tests for the note repository (SQL layer) against in-memory SQLite."""

from __future__ import annotations

from app.notes.models import Note, NoteCitation, NoteSection, Tag
from app.notes.repository import NoteRepository
from app.notes.schemas import ArchivedFilter, PinnedFilter, SortField, SortOrder, StatusFilter


def _note(repo, owner="u1", ws="w1", **kw):
    return repo.create(Note(owner_id=owner, workspace_id=ws, **kw))


def test_create_get_scoping(db_session):
    repo = NoteRepository(db_session)
    n = _note(repo, title="A", content="hello world")
    assert repo.get(n.id, "u1").title == "A"
    assert repo.get(n.id, "other") is None          # owner-scoped
    assert repo.get_by_id_only(n.id).id == n.id      # runner path (no owner)


def test_soft_delete_hides_from_get_and_list(db_session):
    repo = NoteRepository(db_session)
    n = _note(repo, title="A")
    repo.soft_delete(n)
    assert repo.get(n.id, "u1") is None
    items, total = repo.list("u1", "w1")
    assert total == 0 and items == []


def test_list_filters_search_pinned_archived_type(db_session):
    repo = NoteRepository(db_session)
    _note(repo, title="Alpha", content="neural networks", note_type="study", is_pinned=True)
    _note(repo, title="Beta", content="databases", note_type="revision", is_archived=True)
    _note(repo, title="Gamma", content="neural pathways")

    # Default excludes archived.
    _items, total = repo.list("u1", "w1")
    assert total == 2
    # Archived filter.
    _items, total = repo.list("u1", "w1", archived=ArchivedFilter.archived)
    assert total == 1
    # Pinned first + pinned filter.
    items, _ = repo.list("u1", "w1")
    assert items[0].title == "Alpha"                 # pinned floats to top
    _items, total = repo.list("u1", "w1", pinned=PinnedFilter.pinned)
    assert total == 1
    # Content search matches body.
    _items, total = repo.list("u1", "w1", search="neural")
    assert total == 2
    # Type filter.
    _items, total = repo.list("u1", "w1", note_type="revision", archived=ArchivedFilter.all)
    assert total == 1


def test_sections_and_citations_roundtrip(db_session):
    repo = NoteRepository(db_session)
    n = _note(repo, title="A")
    sec = NoteSection(note_id=n.id, heading="H1", order=1, content="body")
    cit = NoteCitation(document_id="doc_x", chunk_id="doc_x:0", page_number=3,
                       workspace_id="w1", citation_text="evidence", confidence=0.9)
    repo.add_section(sec, [cit])
    secs = repo.sections(n.id)
    cits = repo.citations(n.id)
    assert len(secs) == 1 and secs[0].heading == "H1"
    assert len(cits) == 1 and cits[0].note_id == n.id and cits[0].note_section_id == secs[0].id


def test_clear_sections_keeps_freestanding_citations(db_session):
    repo = NoteRepository(db_session)
    n = _note(repo, title="A")
    repo.add_section(NoteSection(note_id=n.id, heading="H", order=1, content="x"),
                     [NoteCitation(document_id="d", workspace_id="w1", citation_text="linked")])
    # A free-standing (edit-time) citation with no section link.
    repo.add_citations(n.id, "w1", [NoteCitation(document_id="d2", citation_text="freestanding")])
    repo.clear_sections(n.id)
    remaining = repo.citations(n.id)
    assert [c.citation_text for c in remaining] == ["freestanding"]   # only section-linked removed
    assert repo.sections(n.id) == []


def test_tags_crud_and_association_counts(db_session):
    repo = NoteRepository(db_session)
    t1 = repo.create_tag(Tag(owner_id="u1", workspace_id="w1", name="ml", color="#111111"))
    t2 = repo.create_tag(Tag(owner_id="u1", workspace_id="w1", name="db", color="#222222"))
    n = _note(repo, title="A")

    repo.set_note_tags(n.id, [t1.id, t2.id])
    assert {t.id for t in repo.tags_for([n.id])[n.id]} == {t1.id, t2.id}
    assert db_session.get(Tag, t1.id).note_count == 1

    # Replace set → t2 removed, count decremented.
    repo.set_note_tags(n.id, [t1.id])
    assert {t.id for t in repo.tags_for([n.id])[n.id]} == {t1.id}
    assert db_session.get(Tag, t2.id).note_count == 0

    # Deleting a tag removes associations.
    repo.delete_tag(db_session.get(Tag, t1.id))
    assert repo.tags_for([n.id]).get(n.id, []) == []


def test_tag_name_exists(db_session):
    repo = NoteRepository(db_session)
    repo.create_tag(Tag(owner_id="u1", workspace_id="w1", name="Machine Learning"))
    assert repo.tag_name_exists("u1", "w1", "machine learning") is True
    assert repo.tag_name_exists("u1", "w1", "other") is False
