"""Sparse retrieval (BM25) over the chunk corpus.

WHY BM25 alongside dense retrieval:
- Dense embeddings capture semantics but miss exact lexical matches — rare terms,
  identifiers, acronyms, numbers, names. BM25 nails those. Fusing the two (hybrid
  search) is consistently stronger than either alone.

DESIGN:
- Single source of truth: the corpus is the VectorStore's metadata list, the same
  records dense retrieval searches. We never maintain a second copy of chunk text,
  so the dense and sparse views can never drift apart.
- rank-bm25's BM25Okapi has no incremental update API; it recomputes corpus stats at
  construction. So `add_documents` / ingestion simply marks the index dirty and the
  next `retrieve` lazily rebuilds. For LexiMind's offline, human-paced ingestion this
  is the right trade: rebuilds are cheap (tokenize N short chunks) and we avoid the
  bug surface of a hand-rolled incremental BM25.
"""

from __future__ import annotations

import re
from typing import List, Optional

from rank_bm25 import BM25Okapi

from app.retrieval.schemas import RetrievalFilter, RetrievedChunk
from app.services.vector_store import VectorStore

# Small English stopword set. Kept inline (no nltk download) to honor offline-first.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "is", "are", "was", "were",
    "be", "been", "being", "of", "to", "in", "on", "for", "with", "as", "by", "at",
    "from", "this", "that", "these", "those", "it", "its", "into", "about", "what",
    "which", "who", "whom", "how", "why", "when", "where", "i", "you", "he", "she",
    "we", "they", "do", "does", "did", "can", "could", "should", "would", "will",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    """Lowercase word/number tokens with stopwords removed.

    Stopword removal helps BM25 focus on content terms; numbers are kept because they
    are often the exact lexical match BM25 is meant to recover.
    """
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS]


class BM25Retriever:
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        self._bm25: Optional[BM25Okapi] = None
        self._built_size: int = -1  # corpus length the current index was built from

    # --- index lifecycle ---------------------------------------------------
    def build(self) -> None:
        """(Re)build the BM25 index from the current corpus. Idempotent."""
        corpus = [tokenize(meta.get("text", "")) for meta in self.vector_store.metadata]
        # BM25Okapi raises on an empty corpus; guard so a fresh install is usable.
        self._bm25 = BM25Okapi(corpus) if corpus else None
        self._built_size = len(corpus)

    def mark_dirty(self) -> None:
        """Signal that the corpus changed; the next retrieve() will rebuild."""
        self._built_size = -1

    def add_documents(self, count: int = 1) -> None:
        """Hook for the ingestion pipeline. We rebuild lazily, so just mark dirty."""
        self.mark_dirty()

    def _ensure_fresh(self) -> None:
        if self._bm25 is None or self._built_size != len(self.vector_store.metadata):
            self.build()

    # --- query -------------------------------------------------------------
    def retrieve(
        self,
        query: str,
        top_k: int,
        *,
        filters: Optional[RetrievalFilter] = None,
    ) -> List[RetrievedChunk]:
        self._ensure_fresh()
        metadata = self.vector_store.metadata
        if self._bm25 is None or not metadata:
            return []

        scores = self._bm25.get_scores(tokenize(query))

        # Rank all docs by score, then over-fetch when filtering (BM25 has no native
        # metadata filter either), then truncate to top_k.
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        results: List[RetrievedChunk] = []
        for idx in order:
            meta = metadata[idx]
            chunk = RetrievedChunk.from_metadata(
                meta,
                score=float(scores[idx]),
                retriever="bm25",
                position=idx,
            )
            if filters is not None and not filters.is_empty() and not filters.matches(meta):
                continue
            results.append(chunk)
            if len(results) >= top_k:
                break

        for rank, chunk in enumerate(results, start=1):
            chunk.rank = rank
        return results
