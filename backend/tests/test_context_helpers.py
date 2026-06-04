"""Shared fixtures/helpers for Phase-2 context-engine tests."""

from app.retrieval.schemas import RetrievedChunk


def mk(chunk_id, text, *, score=0.0, source="d.pdf", document_id="doc_d",
       page_number=1, section=None, start_paragraph=0, end_paragraph=0, **extra):
    meta = {
        "chunk_id": chunk_id,
        "source": source,
        "filename": source,
        "document_id": document_id,
        "page_number": page_number,
        "section": section,
        "section_heading": section,
        "start_paragraph": start_paragraph,
        "end_paragraph": end_paragraph,
        **extra,
    }
    return RetrievedChunk(chunk_id=chunk_id, text=text, metadata=meta, score=score, retriever="reranker")
