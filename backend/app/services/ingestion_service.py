"""Document ingestion: extract -> chunk -> enrich metadata -> embed -> index.

WHY this module exists:
- Ingestion logic lived inline in the upload HTTP route, mixing transport concerns with
  pipeline logic and embedding+saving inside the per-chunk loop (the FAISS index + 6MB
  JSON were rewritten on *every* chunk — O(n^2) I/O for a single upload).
- Centralizing it here gives one tested path that the route, scripts, and tests share,
  and is where Phase-1 METADATA ENRICHMENT happens: every chunk now carries chunk_id,
  document_id, filename, topic, and created_at in addition to the existing fields.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.schemas import derive_chunk_id, derive_document_id
from app.services.chunking_service import chunk_text
from app.services.embedding_service import generate_embeddings
from app.services.pdf_service import extract_text_from_pdf
from app.services.vector_store import VectorStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_chunk_metadata(chunk: Dict[str, Any], *, filename: str, created_at: str) -> Dict[str, Any]:
    """Produce the enriched, Phase-1 metadata record for a single chunk.

    Schema (every chunk now guarantees these keys):
        chunk_id, document_id, source, filename, page_number, section,
        topic, created_at, chunk_index, start_paragraph, end_paragraph, text
    """
    document_id = derive_document_id(filename)
    chunk_index = chunk["chunk_index"]
    section = chunk.get("section_heading")
    return {
        "chunk_id": derive_chunk_id(filename, chunk_index),
        "document_id": document_id,
        "source": filename,          # kept for backward compatibility with old records
        "filename": filename,
        "page_number": chunk["page_number"],
        "section": section,
        "section_heading": section,  # legacy alias still read by answer_service.format_sources
        # Lightweight topic = nearest section heading. A richer topic model can replace
        # this later without changing the schema.
        "topic": section,
        "created_at": created_at,
        "chunk_index": chunk_index,
        "start_paragraph": chunk.get("start_paragraph"),
        "end_paragraph": chunk.get("end_paragraph"),
        "text": chunk["text"],
    }


def ingest_pdf(
    file_path: str,
    filename: str,
    vector_store: VectorStore,
    bm25_retriever: BM25Retriever | None = None,
) -> Dict[str, Any]:
    """Full ingestion for one PDF. Returns a summary dict for the API response."""
    extracted_pages = extract_text_from_pdf(file_path)
    chunks = chunk_text(extracted_pages)

    if not chunks:
        vector_store.save()
        return {
            "filename": filename,
            "document_id": derive_document_id(filename),
            "pages_extracted": len(extracted_pages),
            "total_chunks": 0,
            "message": "No extractable text chunks found in PDF.",
        }

    created_at = _now_iso()
    texts = [c["text"] for c in chunks]
    embeddings = generate_embeddings(texts)  # one batched encode call

    for chunk, embedding in zip(chunks, embeddings):
        metadata = build_chunk_metadata(chunk, filename=filename, created_at=created_at)
        vector_store.add(embedding, metadata)

    # Persist once per document (not once per chunk).
    vector_store.save()

    # Keep the sparse index in sync with the new corpus.
    if bm25_retriever is not None:
        bm25_retriever.add_documents(len(chunks))

    return {
        "filename": filename,
        "document_id": derive_document_id(filename),
        "pages_extracted": len(extracted_pages),
        "total_chunks": len(chunks),
        "message": "PDF processed and indexed successfully",
    }
