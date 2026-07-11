"""Unit tests for the citation indexer: aggregation, dedup, references, knowledge edges."""

from __future__ import annotations

from app.citations.indexer import CitationIndexer
from app.citations.models import Citation, CitationReference, KnowledgeReference
from app.chat.models import Conversation, Message, MessageCitation
from app.notes.models import Note, NoteCitation
from app.summaries.models import Summary, SummaryCitation, SummarySection
from sqlalchemy import select


def _seed_note(db, ws="w1", owner="u1", chunks=(("doc_x:0", 3), ("doc_x:9", 20))):
    note = Note(workspace_id=ws, owner_id=owner, title="My Note", content="x", status="ready")
    db.add(note); db.flush()
    for cid, page in chunks:
        db.add(NoteCitation(note_id=note.id, document_id="doc_x", chunk_id=cid, page_number=page,
                            workspace_id=ws, citation_text=f"note evidence {cid}", confidence=0.8))
    db.commit()
    return note


def _seed_summary(db, ws="w1", owner="u1", chunks=(("doc_x:0", 3), ("doc_x:9", 20))):
    s = Summary(workspace_id=ws, owner_id=owner, title="My Summary", status="completed")
    db.add(s); db.flush()
    sec = SummarySection(summary_id=s.id, heading="Overview", order=1, content="body")
    db.add(sec); db.flush()
    for cid, page in chunks:
        db.add(SummaryCitation(summary_section_id=sec.id, document_id="doc_x", chunk_id=cid,
                               page_number=page, workspace_id=ws, citation_text=f"sum evidence {cid}", confidence=0.9))
    db.commit()
    return s


def test_rebuild_unifies_chunks_across_modules(db_session):
    _seed_note(db_session)
    _seed_summary(db_session)
    n = CitationIndexer(db_session).rebuild("w1", "u1")
    # Two distinct chunks → two unified citations (even though 4 source rows reference them).
    assert n == 2
    cits = list(db_session.scalars(select(Citation).where(Citation.workspace_id == "w1")))
    assert {c.chunk_id for c in cits} == {"doc_x:0", "doc_x:9"}
    # Each chunk is referenced by a note AND a summary → reference_count 2.
    for c in cits:
        assert c.reference_count == 2
        assert c.confidence == 0.9  # max(note 0.8, summary 0.9)


def test_references_are_typed_and_labeled(db_session):
    _seed_note(db_session)
    _seed_summary(db_session)
    CitationIndexer(db_session).rebuild("w1", "u1")
    refs = list(db_session.scalars(select(CitationReference).where(CitationReference.workspace_id == "w1")))
    assert len(refs) == 4  # 2 note + 2 summary
    types = {r.reference_type for r in refs}
    assert types == {"note", "summary"}
    note_ref = next(r for r in refs if r.reference_type == "note")
    assert note_ref.note_id and note_ref.ref_title == "My Note"


def test_co_reference_edges_between_cochunks(db_session):
    # A note referencing two chunks → the two chunks co-occur → co_reference edges both ways.
    _seed_note(db_session)
    CitationIndexer(db_session).rebuild("w1", "u1")
    edges = list(db_session.scalars(
        select(KnowledgeReference).where(KnowledgeReference.relationship == "co_reference")
    ))
    assert len(edges) == 2  # a→b and b→a
    assert all(e.strength == 1.0 for e in edges)


def test_same_document_edges_when_not_cooccurring(db_session):
    # Two separate notes, each citing ONE distinct chunk → no co-occurrence, but same document.
    _seed_note(db_session, chunks=(("doc_x:1", 1),))
    _seed_note(db_session, chunks=(("doc_x:2", 2),))
    CitationIndexer(db_session).rebuild("w1", "u1")
    rels = {e.relationship for e in db_session.scalars(select(KnowledgeReference))}
    assert "same_document" in rels


def test_rebuild_is_idempotent(db_session):
    _seed_summary(db_session)
    idx = CitationIndexer(db_session)
    idx.rebuild("w1", "u1")
    first = idx.indexed_reference_count("w1")
    idx.rebuild("w1", "u1")  # rebuild again
    assert idx.indexed_reference_count("w1") == first  # no duplication


def test_staleness_counts_match_sources(db_session):
    _seed_note(db_session)
    idx = CitationIndexer(db_session)
    assert idx.indexed_reference_count("w1") == 0
    assert idx.source_reference_count("w1") == 2  # two note citations
    idx.rebuild("w1", "u1")
    assert idx.indexed_reference_count("w1") == 2  # now in sync


def test_soft_deleted_parents_excluded(db_session):
    note = _seed_note(db_session)
    note.deleted_at = __import__("datetime").datetime(2026, 1, 1)
    db_session.commit()
    n = CitationIndexer(db_session).rebuild("w1", "u1")
    assert n == 0  # a deleted note contributes no citations
