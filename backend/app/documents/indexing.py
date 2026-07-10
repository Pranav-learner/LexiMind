"""Cross-store index operations for a document (Document row ↔ FAISS/BM25 chunks).

These helpers are the ONLY bridge between the relational document layer and the retrieval
layer. They take the `vector_store` / `bm25_retriever` singletons as parameters (injected by
the API route) so this module — and the whole documents package — never imports faiss and
stays testable in the light environment.

Linkage: a document's chunks are exactly the vector-metadata records whose
`document_id == doc.vector_document_id` AND `workspace_id == doc.workspace_id`. Scoping by both
prevents two workspaces that uploaded a file with the same name (same derived vector id) from
counting/deleting each other's chunks.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from app.documents.models import Document
from app.documents.schemas import IndexHealth


def chunk_predicate(vector_document_id: str, workspace_id: str | None) -> Callable[[Dict[str, Any]], bool]:
    def _match(meta: Dict[str, Any]) -> bool:
        if meta.get("document_id") != vector_document_id:
            return False
        # Workspace-less legacy chunks (workspace_id is None) only match a None scope.
        return meta.get("workspace_id") == workspace_id
    return _match


def count_chunks(vector_store, vector_document_id: str, workspace_id: str | None) -> int:
    return vector_store.count_where(chunk_predicate(vector_document_id, workspace_id))


def list_document_chunks(
    vector_store,
    vector_document_id: str,
    workspace_id: str | None,
    *,
    page: int | None = None,
) -> list[dict]:
    """Return a document's chunk metadata records, sorted by (page_number, chunk_index).

    Optionally filtered to a single `page`. Powers the viewer's citation highlighting,
    section outline, and per-page text lookup. Read-only over the vector metadata list.
    """
    match = chunk_predicate(vector_document_id, workspace_id)
    records = [m for m in vector_store.metadata if match(m)]
    if page is not None:
        records = [m for m in records if m.get("page_number") == page]

    def _key(m):
        return (m.get("page_number") or 0, m.get("chunk_index") or 0)

    return sorted(records, key=_key)


def remove_document_chunks(
    vector_store,
    bm25_retriever,
    vector_document_id: str,
    workspace_id: str | None,
) -> int:
    """Delete a document's chunks from FAISS + BM25 and persist. Returns count removed."""
    removed = vector_store.remove_where(chunk_predicate(vector_document_id, workspace_id))
    if removed:
        vector_store.save()
        if bm25_retriever is not None:
            bm25_retriever.mark_dirty()  # lazy rebuild picks up the smaller corpus
    return removed


def compute_index_health(vector_store, bm25_retriever, document: Document) -> IndexHealth:
    """Live probe of the document's presence in the retrieval indexes."""
    live_chunks = count_chunks(vector_store, document.vector_document_id, document.workspace_id)

    faiss_consistent = getattr(vector_store.index, "ntotal", None) == vector_store.size()
    faiss_status = "indexed" if live_chunks > 0 and faiss_consistent else (
        "missing" if live_chunks == 0 else "unknown"
    )
    bm25_status = "indexed" if (bm25_retriever is not None and live_chunks > 0) else (
        "missing" if live_chunks == 0 else "unknown"
    )

    if live_chunks == 0:
        health = "empty"
    elif faiss_status == "indexed" and bm25_status == "indexed":
        health = "healthy"
    else:
        health = "degraded"

    return IndexHealth(
        chunk_count=live_chunks,
        embedding_count=live_chunks,  # one vector per chunk in an IndexFlatL2
        faiss_status=faiss_status,
        bm25_status=bm25_status,
        index_health=health,
    )
