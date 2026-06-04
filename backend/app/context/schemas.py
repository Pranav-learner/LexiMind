"""Working types for the context engine.

WHY a separate `Evidence` type instead of mutating `RetrievedChunk`:
- The retrieval layer's `RetrievedChunk` is its stable output contract. The context
  stages need to annotate items (evidence score, compressed text, "merged from" lineage)
  WITHOUT polluting that contract. `Evidence` wraps a chunk and carries those annotations.
- It also makes CITATION PRESERVATION (Task 6) explicit and testable: every Evidence owns
  a non-empty list of `Citation`s, and merging two pieces of evidence unions their
  citations rather than dropping any.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.retrieval.schemas import RetrievedChunk


@dataclass(frozen=True)
class Citation:
    """The minimal, must-never-be-lost provenance for a piece of evidence."""

    chunk_id: str
    document_id: Optional[str]
    source: Optional[str]
    page_number: Optional[int]
    section: Optional[str] = None

    @classmethod
    def from_metadata(cls, meta: Dict[str, Any], chunk_id: str) -> "Citation":
        return cls(
            chunk_id=chunk_id,
            document_id=meta.get("document_id"),
            source=meta.get("source") or meta.get("filename"),
            page_number=meta.get("page_number"),
            section=meta.get("section") or meta.get("section_heading"),
        )

    def is_complete(self) -> bool:
        """A citation is 'complete' when it can point a reader to an exact location."""
        return bool(self.chunk_id and self.document_id and self.source and self.page_number is not None)


@dataclass
class Evidence:
    """One unit of context flowing through the engine.

    `text` starts as the chunk's text and may be replaced by a compressed/merged form.
    `citations` always reflects every source chunk that contributed to `text`.
    """

    chunk: RetrievedChunk
    text: str
    citations: List[Citation]
    evidence_score: float = 0.0
    retrieval_score: float = 0.0
    compressed: bool = False
    merged_from: List[str] = field(default_factory=list)

    @classmethod
    def from_chunk(cls, chunk: RetrievedChunk) -> "Evidence":
        cit = Citation.from_metadata(chunk.metadata, chunk.chunk_id)
        return cls(
            chunk=chunk,
            text=chunk.text,
            citations=[cit],
            retrieval_score=float(chunk.score),
            evidence_score=float(chunk.score),
        )

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id

    @property
    def document_id(self) -> Optional[str]:
        return self.chunk.metadata.get("document_id")

    @property
    def page_number(self) -> Optional[int]:
        return self.chunk.metadata.get("page_number")

    @property
    def start_paragraph(self) -> Optional[int]:
        return self.chunk.metadata.get("start_paragraph")


@dataclass
class ContextResult:
    """Output of ContextBuilderService: the LLM-ready context plus full accounting."""

    context: str
    evidence: List[Evidence]
    citations: List[Citation]
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def num_chunks_used(self) -> int:
        return len(self.evidence)
