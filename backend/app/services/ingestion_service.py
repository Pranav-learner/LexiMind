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
from typing import Any, Callable, Dict, List, Optional

from app.core.config import settings
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.schemas import derive_chunk_id, derive_document_id
from app.services.chunking_service import chunk_text
from app.services.embedding_service import generate_embeddings
from app.services.pdf_service import extract_text_from_pdf
from app.services.vector_store import VectorStore

# A stage callback lets the Document Library surface real per-stage progress
# (text_extraction → chunking → embedding → faiss_indexing → bm25_indexing → metadata).
StageCallback = Optional[Callable[[str], None]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(on_stage: StageCallback, stage: str) -> None:
    if on_stage is not None:
        on_stage(stage)


def build_chunk_metadata(
    chunk: Dict[str, Any],
    *,
    filename: str,
    created_at: str,
    workspace_id: str | None = None,
) -> Dict[str, Any]:
    """Produce the enriched metadata record for a single chunk.

    Schema (every chunk now guarantees these keys):
        chunk_id, document_id, source, filename, page_number, section,
        topic, created_at, chunk_index, start_paragraph, end_paragraph, text, workspace_id

    Phase 3: `workspace_id` binds a chunk to its owning workspace so retrieval can isolate
    results per workspace. It is nullable for backward compatibility — legacy chunks and
    workspace-less uploads carry `None` (see scripts/migrate_workspace.py for the backfill).
    """
    document_id = derive_document_id(filename)
    chunk_index = chunk["chunk_index"]
    section = chunk.get("section_heading")
    return {
        "chunk_id": derive_chunk_id(filename, chunk_index),
        "document_id": document_id,
        "source": filename,          # kept for backward compatibility with old records
        "filename": filename,
        "workspace_id": workspace_id,
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
    *,
    workspace_id: str | None = None,
    on_stage: StageCallback = None,
    replace_existing: bool = False,
) -> Dict[str, Any]:
    """Full ingestion for one PDF. Returns a summary dict for the API response.

    `on_stage(stage)` is invoked as the pipeline advances so the Document Library can surface
    real per-stage progress. `replace_existing=True` first removes any chunks already indexed
    for this (document_id, workspace_id) so re-uploads / re-indexing are idempotent instead of
    duplicating content (used by the document upload + re-index paths).
    """
    document_id = derive_document_id(filename)

    if replace_existing:
        def _existing(meta: Dict[str, Any]) -> bool:
            return meta.get("document_id") == document_id and meta.get("workspace_id") == workspace_id

        if vector_store.remove_where(_existing) and bm25_retriever is not None:
            bm25_retriever.mark_dirty()

    _emit(on_stage, "text_extraction")
    extracted_pages = extract_text_from_pdf(file_path)

    _emit(on_stage, "chunking")
    chunks = chunk_text(extracted_pages)

    if not chunks:
        vector_store.save()
        return {
            "filename": filename,
            "document_id": document_id,
            "workspace_id": workspace_id,
            "pages_extracted": len(extracted_pages),
            "total_chunks": 0,
            "word_count": 0,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dim,
            "message": "No extractable text chunks found in PDF.",
        }

    created_at = _now_iso()
    texts = [c["text"] for c in chunks]

    _emit(on_stage, "embedding")
    embeddings = generate_embeddings(texts)  # one batched encode call

    _emit(on_stage, "faiss_indexing")
    for chunk, embedding in zip(chunks, embeddings):
        metadata = build_chunk_metadata(
            chunk, filename=filename, created_at=created_at, workspace_id=workspace_id
        )
        vector_store.add(embedding, metadata)

    # Persist once per document (not once per chunk).
    vector_store.save()

    # Keep the sparse index in sync with the new corpus.
    _emit(on_stage, "bm25_indexing")
    if bm25_retriever is not None:
        bm25_retriever.add_documents(len(chunks))

    _emit(on_stage, "metadata")
    word_count = sum(len(t.split()) for t in texts)

    return {
        "filename": filename,
        "document_id": document_id,
        "workspace_id": workspace_id,
        "pages_extracted": len(extracted_pages),
        "total_chunks": len(chunks),
        "word_count": word_count,
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dim,
        # Raw material the documents layer interprets (e.g. language guess). Kept small.
        "sample_text": " ".join(texts)[:2000],
        "message": "PDF processed and indexed successfully",
    }
