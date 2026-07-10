"""Shared data structures for the retrieval layer.

WHY this exists:
- Before Phase 1, retrieval results were bare `dict`s with ad-hoc keys ("score",
  "page_number", ...). Each consumer (answer_service, query route) reached into the
  dict with .get() and guessed at shape. That is fragile and untestable.
- `RetrievedChunk` gives every retriever (dense, sparse, hybrid, reranked) a single
  typed shape to return, so fusion / filtering / reranking can be written once and
  composed. It is intentionally tolerant of LEGACY metadata (the 2.4k chunks indexed
  before metadata enrichment lack chunk_id/document_id/topic/created_at).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Union

FilterValue = Optional[Union[str, List[str]]]


def derive_document_id(source: str) -> str:
    """Stable id for a document, derived from its filename.

    Deterministic so that legacy records and freshly ingested records for the same
    file collapse to the same document_id (needed for metadata filtering to work on
    the existing index without a full re-ingest).
    """
    return "doc_" + hashlib.sha1((source or "unknown").encode("utf-8")).hexdigest()[:12]


def derive_chunk_id(source: str, chunk_index: Any) -> str:
    """Stable id for a chunk within a document."""
    return f"{derive_document_id(source)}:{chunk_index}"


@dataclass
class RetrievedChunk:
    """One retrieval candidate, carrying its text, full metadata, and provenance.

    `score` and `rank` are per-retriever. After fusion the chunk carries a fused
    `score`; after reranking it carries the cross-encoder score. `retriever` records
    where the candidate originated ("dense", "bm25", "hybrid", "reranker") which is
    invaluable when debugging why a chunk surfaced.
    """

    chunk_id: str
    text: str
    metadata: Dict[str, Any]
    score: float = 0.0
    rank: int = 0
    retriever: str = ""

    # Convenience accessors (read from metadata, tolerant of legacy/missing keys).
    @property
    def document_id(self) -> Optional[str]:
        return self.metadata.get("document_id")

    @property
    def source(self) -> Optional[str]:
        return self.metadata.get("source")

    @property
    def page_number(self) -> Optional[int]:
        return self.metadata.get("page_number")

    @property
    def topic(self) -> Optional[str]:
        return self.metadata.get("topic")

    @classmethod
    def from_metadata(
        cls,
        meta: Dict[str, Any],
        *,
        score: float = 0.0,
        rank: int = 0,
        retriever: str = "",
        position: Optional[int] = None,
    ) -> "RetrievedChunk":
        """Build a RetrievedChunk from a stored metadata dict.

        Backfills a chunk_id for legacy records that predate metadata enrichment so
        that fusion (which dedups by chunk_id) still works on the existing index.
        `position` is the index of the record in the metadata list — used as a last
        resort to guarantee uniqueness when chunk_index is also missing.
        """
        chunk_id = meta.get("chunk_id")
        if not chunk_id:
            source = meta.get("source", "unknown")
            idx = meta.get("chunk_index", position if position is not None else id(meta))
            chunk_id = derive_chunk_id(source, idx)
        return cls(
            chunk_id=chunk_id,
            text=meta.get("text", ""),
            metadata=meta,
            score=score,
            rank=rank,
            retriever=retriever,
        )


@dataclass
class RetrievalFilter:
    """Declarative metadata filter applied to retrieval candidates.

    Each field may be a single value or a list of accepted values (OR within a field,
    AND across fields). Designed to extend cleanly to future facets (modality, date
    ranges) without changing call sites — callers pass a RetrievalFilter or None.
    """

    document_id: FilterValue = None
    # `workspace_id` is the Phase-3 canonical facet (matches metadata["workspace_id"]).
    # `workspace` is kept as a legacy alias so pre-Phase-3 callers don't break.
    workspace_id: FilterValue = None
    workspace: FilterValue = None
    source: FilterValue = None
    topic: FilterValue = None
    # Phase-3 Module-2: NEGATIVE facet. A chunk whose document_id is in this set is excluded.
    # Used to keep ARCHIVED documents out of normal retrieval without mutating the vector store.
    exclude_document_id: FilterValue = None

    def is_empty(self) -> bool:
        return not any(
            [
                self.document_id,
                self.workspace_id,
                self.workspace,
                self.source,
                self.topic,
                self.exclude_document_id,
            ]
        )

    @staticmethod
    def _field_matches(allowed: FilterValue, value: Any) -> bool:
        if allowed is None:
            return True  # field not constrained
        if isinstance(allowed, str):
            allowed = [allowed]
        return value in set(allowed)

    @staticmethod
    def _field_excludes(excluded: FilterValue, value: Any) -> bool:
        """True if `value` is barred by an exclusion set (never bars when unset)."""
        if excluded is None:
            return False
        if isinstance(excluded, str):
            excluded = [excluded]
        return value in set(excluded)

    def matches(self, meta: Dict[str, Any]) -> bool:
        # workspace_id matches against metadata["workspace_id"]; the legacy `workspace`
        # facet also matches metadata["workspace_id"] so old-style callers still filter.
        workspace_value = meta.get("workspace_id")
        if self._field_excludes(self.exclude_document_id, meta.get("document_id")):
            return False
        return (
            self._field_matches(self.document_id, meta.get("document_id"))
            and self._field_matches(self.workspace_id, workspace_value)
            and self._field_matches(self.workspace, meta.get("workspace", workspace_value))
            and self._field_matches(self.source, meta.get("source"))
            and self._field_matches(self.topic, meta.get("topic"))
        )

    def apply(self, chunks: Iterable[RetrievedChunk]) -> List[RetrievedChunk]:
        if self.is_empty():
            return list(chunks)
        return [c for c in chunks if self.matches(c.metadata)]
