"""Unit tests for the structured-citation helper the PDF Viewer consumes (Module 3)."""

from __future__ import annotations

from app.context.schemas import Citation, Evidence
from app.retrieval.schemas import RetrievedChunk
from app.services.answer_service import structured_citations


def _evidence(chunk_id, document_id, source, page, text, section=None):
    chunk = RetrievedChunk(chunk_id=chunk_id, text=text, metadata={"document_id": document_id})
    cit = Citation(chunk_id=chunk_id, document_id=document_id, source=source, page_number=page, section=section)
    return Evidence(chunk=chunk, text=text, citations=[cit])


def test_structured_citations_shape_and_fields():
    ev = _evidence("doc_a:0", "doc_a", "OS.pdf", 142, "virtual memory paging", section="Memory")
    out = structured_citations([ev])
    assert len(out) == 1
    c = out[0]
    assert c["chunk_id"] == "doc_a:0"
    assert c["document_id"] == "doc_a"
    assert c["source"] == "OS.pdf"
    assert c["page_number"] == 142
    assert c["section"] == "Memory"
    assert c["text"] == "virtual memory paging"


def test_structured_citations_dedup_by_chunk_id_preserves_order():
    e1 = _evidence("doc_a:0", "doc_a", "OS.pdf", 1, "alpha")
    e2 = _evidence("doc_b:3", "doc_b", "ML.pdf", 9, "beta")
    dup = _evidence("doc_a:0", "doc_a", "OS.pdf", 1, "alpha again")
    out = structured_citations([e1, e2, dup])
    assert [c["chunk_id"] for c in out] == ["doc_a:0", "doc_b:3"]


def test_structured_citations_truncates_long_text():
    ev = _evidence("c:0", "d", "x.pdf", 1, "z" * 1000)
    assert len(structured_citations([ev])[0]["text"]) == 400
