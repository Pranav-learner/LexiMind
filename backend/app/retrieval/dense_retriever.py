"""Dense (semantic) retrieval — a thin adapter over the FAISS VectorStore.

WHY a separate class instead of calling VectorStore.search directly:
- Gives dense retrieval the same interface as BM25 (returns RetrievedChunk with a
  rank), so HybridRetriever and RRF can treat both uniformly.
- Centralizes the "over-fetch then filter" pattern needed for metadata filtering,
  since FAISS IndexFlatL2 has no native metadata filter.
"""

from __future__ import annotations

from typing import List, Optional

from app.retrieval.schemas import RetrievalFilter, RetrievedChunk
from app.services.vector_store import VectorStore


class DenseRetriever:
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store

    def retrieve(
        self,
        query_embedding: List[float],
        top_k: int,
        *,
        filters: Optional[RetrievalFilter] = None,
    ) -> List[RetrievedChunk]:
        """Return up to top_k dense candidates ordered best-first.

        When a filter is active we over-fetch (3x, capped) before filtering so that
        post-filter we still return roughly top_k results despite FAISS lacking
        server-side filtering.
        """
        fetch = top_k
        if filters is not None and not filters.is_empty():
            fetch = min(max(top_k * 3, top_k + 20), max(self.vector_store.size(), 1))

        raw = self.vector_store.search(query_embedding, top_k=fetch)

        chunks: List[RetrievedChunk] = []
        for position, meta in enumerate(raw):
            chunk = RetrievedChunk.from_metadata(
                meta,
                score=float(meta.get("score", 0.0)),
                retriever="dense",
                position=position,
            )
            chunks.append(chunk)

        if filters is not None and not filters.is_empty():
            chunks = filters.apply(chunks)

        chunks = chunks[:top_k]
        for rank, chunk in enumerate(chunks, start=1):
            chunk.rank = rank
        return chunks
