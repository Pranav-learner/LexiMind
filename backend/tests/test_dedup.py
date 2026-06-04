"""Unit tests for DuplicateChunkDetector."""

from app.context.dedup import DuplicateChunkDetector
from app.context.schemas import Evidence
from tests.test_context_helpers import mk


def _ev(chunk_id, text, *, score=0.0, **kw):
    e = Evidence.from_chunk(mk(chunk_id, text, score=score, **kw))
    e.evidence_score = score
    return e


def test_exact_duplicate_removed_keeps_higher_score():
    a = _ev("a", "the cat sat on the mat", score=0.9)
    b = _ev("b", "the cat sat on the mat", score=0.3)
    kept, removed = DuplicateChunkDetector().detect([a, b])
    assert [e.chunk_id for e in kept] == ["a"]      # higher score survives
    assert [e.chunk_id for e in removed] == ["b"]


def test_near_duplicate_by_jaccard():
    a = _ev("a", "operating systems schedule processes and threads efficiently", score=0.8)
    b = _ev("b", "operating systems schedule processes and threads", score=0.5)
    kept, removed = DuplicateChunkDetector(threshold=0.7).detect([a, b])
    assert [e.chunk_id for e in kept] == ["a"]
    assert removed[0].chunk_id == "b"


def test_structural_duplicate_same_doc_page_overlapping_paragraphs():
    a = _ev("a", "Completely different words here about scheduling.", score=0.9,
            document_id="doc_os", page_number=5, start_paragraph=1, end_paragraph=3)
    b = _ev("b", "Totally unrelated lexical content entirely.", score=0.4,
            document_id="doc_os", page_number=5, start_paragraph=2, end_paragraph=4)
    kept, removed = DuplicateChunkDetector(threshold=0.99).detect([a, b])
    assert [e.chunk_id for e in kept] == ["a"]      # overlapping paragraph ranges -> dup
    assert removed[0].chunk_id == "b"


def test_distinct_chunks_all_kept():
    a = _ev("a", "java generics and collections", score=0.7, document_id="doc_j", page_number=1)
    b = _ev("b", "the cat sat on the mat", score=0.6, document_id="doc_p", page_number=2)
    kept, removed = DuplicateChunkDetector().detect([a, b])
    assert {e.chunk_id for e in kept} == {"a", "b"}
    assert removed == []
