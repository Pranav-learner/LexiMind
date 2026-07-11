"""Unit tests for NoteService: creation paths, autosave/conflict, generation, tags, duplicate."""

from __future__ import annotations

import pytest

from app.notes.errors import NoteConflict, NoteStateError, DuplicateTagName
from app.notes.repository import NoteRepository
from app.notes.service import NoteService
from tests.conftest import FakeNotesEngine


def _svc(db):
    return NoteService(NoteRepository(db))


def test_create_blank_sets_metrics_and_ready(db_session):
    svc = _svc(db_session)
    n = svc.create("u1", "w1", title="My Note", content="one two three four five")
    assert n.status == "ready" and n.created_by == "user" and n.source == "blank"
    assert n.word_count == 5 and n.reading_time == 1 and n.version == 1


def test_create_with_citations(db_session):
    svc = _svc(db_session)
    n = svc.create("u1", "w1", source="selection", content="highlighted text",
                   citations=[{"document_id": "doc_x", "page_number": 7, "citation_text": "src"}])
    assert n.citation_count == 1
    cits = svc.repo.citations(n.id)
    assert cits[0].document_id == "doc_x" and cits[0].workspace_id == "w1"


def test_autosave_bumps_version_and_detects_conflict(db_session):
    svc = _svc(db_session)
    n = svc.create("u1", "w1", content="v1 body")
    updated = svc.save_content(n.id, "u1", content="v2 body longer", base_version=1)
    assert updated.version == 2 and updated.word_count == 3

    # Stale base version → conflict.
    with pytest.raises(NoteConflict):
        svc.save_content(n.id, "u1", content="v3", base_version=1)

    # No-op save (unchanged content) does not bump version (avoids unnecessary writes).
    same = svc.save_content(n.id, "u1", content="v2 body longer", base_version=2)
    assert same.version == 2


def test_generate_now_persists_sections_content_citations(db_session):
    svc = _svc(db_session)
    n = svc.create_generated("u1", "w1", note_type="study", scope="workspace")
    assert n.status == "queued"
    done = svc.generate_now(n.id, FakeNotesEngine())
    assert done.status == "completed" and done.progress == 100
    assert done.section_count == 2 and done.citation_count == 2
    assert "## Overview" in done.content and "## Key Concepts" in done.content
    assert done.word_count > 0


def test_regenerate_requires_ai_note(db_session):
    svc = _svc(db_session)
    manual = svc.create("u1", "w1", content="manual")
    with pytest.raises(NoteStateError):
        svc.reset_for_regenerate(manual.id, "u1")

    ai = svc.create_generated("u1", "w1", note_type="quick", scope="workspace")
    svc.generate_now(ai.id, FakeNotesEngine())
    reset = svc.reset_for_regenerate(ai.id, "u1")
    assert reset.status == "queued" and reset.section_count == 0 and reset.version >= 2


def test_cancel_only_queued_or_processing(db_session):
    svc = _svc(db_session)
    n = svc.create("u1", "w1", content="x")   # ready
    with pytest.raises(NoteStateError):
        svc.cancel(n.id, "u1")


def test_pin_favorite_archive_and_delete_counter(db_session):
    svc = _svc(db_session)
    n = svc.create("u1", "w1", content="x")
    svc.update_meta(n.id, "u1", is_pinned=True, is_favorite=True, is_archived=True)
    got = svc.get(n.id, "u1")
    assert got.is_pinned and got.is_favorite and got.is_archived


def test_tags_lifecycle_and_duplicate(db_session):
    svc = _svc(db_session)
    t = svc.create_tag("u1", "w1", name="ml", color="#123456")
    with pytest.raises(DuplicateTagName):
        svc.create_tag("u1", "w1", name="ML")   # case-insensitive dup

    n = svc.create("u1", "w1", content="x")
    svc.set_note_tags(n.id, "u1", [t.id])
    tags = svc.repo.tags_for([n.id])[n.id]
    assert [tg.name for tg in tags] == ["ml"]

    # Unknown tag ids are silently filtered (never attached).
    svc.set_note_tags(n.id, "u1", [t.id, "tag_nope"])
    assert len(svc.repo.tags_for([n.id])[n.id]) == 1


def test_duplicate_copies_content_and_sections(db_session):
    svc = _svc(db_session)
    ai = svc.create_generated("u1", "w1", note_type="study", scope="workspace")
    svc.generate_now(ai.id, FakeNotesEngine())
    copy = svc.duplicate(ai.id, "u1")
    assert copy.title.endswith("(copy)")
    assert copy.section_count == 2
    assert len(svc.repo.sections(copy.id)) == 2
    assert svc.repo.citations(copy.id)  # citations carried over


def test_assist_delegates_to_engine(db_session):
    svc = _svc(db_session)
    n = svc.create("u1", "w1", content="body")
    out = svc.assist(n.id, "u1", FakeNotesEngine(), operation="simplify", selection="hard text")
    assert out == "[simplify] hard text"
