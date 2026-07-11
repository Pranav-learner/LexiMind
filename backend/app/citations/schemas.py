"""Citation-intelligence DTOs + list query enums (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class ReferenceType(str, Enum):
    message = "message"
    summary = "summary"
    note = "note"
    flashcard = "flashcard"


class CitationSortField(str, Enum):
    confidence = "confidence"
    reference_count = "reference_count"
    created_at = "created_at"
    page_number = "page_number"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


# --------------------------------------------------------------------- outputs
class ReferenceOut(BaseModel):
    id: str
    reference_type: str
    message_id: Optional[str]
    summary_id: Optional[str]
    note_id: Optional[str]
    flashcard_id: Optional[str]
    ref_parent_id: Optional[str]
    ref_child_id: Optional[str]
    ref_title: str

    model_config = {"from_attributes": True}


class CitationOut(BaseModel):
    """Compact citation for lists/search."""

    id: str
    workspace_id: str
    document_id: Optional[str]
    chunk_id: Optional[str]
    page_number: Optional[int]
    paragraph_number: Optional[int]
    citation_text: str
    confidence: Optional[float]
    retrieval_score: Optional[float]
    reranker_score: Optional[float]
    evidence_score: Optional[float]
    reference_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class RelatedCitation(BaseModel):
    citation_id: Optional[str]
    chunk_id: Optional[str]
    document_id: Optional[str]
    relationship: str
    strength: float
    page_number: Optional[int] = None
    citation_text: str = ""


class DocumentContext(BaseModel):
    document_id: Optional[str]         # vector id (resolve via /documents/by-vector)
    citation_count: int                # how many indexed citations this document produced
    reference_count: int               # total references across those citations


class CitationDetail(CitationOut):
    """Full citation intelligence: references grouped by type + document context."""

    references: List[ReferenceOut] = []
    references_by_type: dict = {}
    document: Optional[DocumentContext] = None


class RelatedKnowledge(BaseModel):
    """The Knowledge Explorer payload for a citation: backlinks + related chunks, grouped."""

    citation_id: str
    related: List[RelatedCitation] = []          # chunk↔chunk neighbours (co_reference/same_document)
    references_by_type: dict = {}                 # counts of each artifact type referencing it
    same_document_citations: List[CitationOut] = []


class ExplainFactor(BaseModel):
    label: str
    detail: str
    score: Optional[float] = None


class CitationExplanation(BaseModel):
    citation_id: str
    summary: str
    factors: List[ExplainFactor] = []
    retrieval_path: List[str] = []


class CitationStats(BaseModel):
    total_citations: int
    total_references: int
    documents_cited: int
    avg_confidence: float
    high_confidence: int                 # citations with confidence >= 0.7
    references_by_type: dict             # {message: n, summary: n, note: n, flashcard: n}
    most_referenced: List[CitationOut] = []


class CitationListResponse(BaseModel):
    items: List[CitationOut]
    total: int
    page: int
    page_size: int
    pages: int
