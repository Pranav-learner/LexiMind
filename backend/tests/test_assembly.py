"""Unit tests for ContextAssembler."""

from app.context.assembly import ContextAssembler
from app.context.schemas import Evidence
from tests.test_context_helpers import mk


def _ev(chunk_id, text, *, score, **kw):
    e = Evidence.from_chunk(mk(chunk_id, text, score=score, **kw))
    e.evidence_score = score
    return e


def test_assemble_numbers_blocks_and_returns_citations():
    ev = [_ev("a", "alpha text", score=0.9, source="A.pdf", document_id="doc_a", page_number=1)]
    text, citations = ContextAssembler().assemble(ev)
    assert text.startswith("[1] A.pdf · Page 1")
    assert "alpha text" in text
    assert len(citations) == 1 and citations[0].chunk_id == "a"


def test_groups_by_document_and_orders_by_score():
    a = _ev("a", "doc A strong", score=0.9, source="A.pdf", document_id="doc_a", page_number=1)
    b = _ev("b", "doc B weak", score=0.2, source="B.pdf", document_id="doc_b", page_number=1)
    text, _ = ContextAssembler().assemble([b, a])
    # Higher-scoring document group leads.
    assert text.index("doc A strong") < text.index("doc B weak")


def test_within_document_orders_by_page_then_paragraph():
    p2 = _ev("p2", "page two", score=0.5, document_id="doc_a", page_number=2, start_paragraph=0)
    p1 = _ev("p1", "page one", score=0.5, document_id="doc_a", page_number=1, start_paragraph=0)
    text, _ = ContextAssembler().assemble([p2, p1])
    assert text.index("page one") < text.index("page two")


def test_empty():
    assert ContextAssembler().assemble([]) == ("", [])
