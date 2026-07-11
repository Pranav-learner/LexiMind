"""Multimodal context DTOs — the internal evidence/block types + the API request/response contracts.

`MMEvidence` is the unit flowing through the pipeline; scores + reasons are filled stage by stage so
the final object carries a COMPLETE explanation (Step 10). `ContextBlock` groups included evidence by
modality for adaptive assembly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

MODALITIES = ("text", "ocr", "image", "diagram", "table", "metadata")


# --------------------------------------------------------------------- internal (mutable)
@dataclass
class MMCitation:
    modality: str
    document_id: Optional[str]
    chunk_id: Optional[str] = None
    asset_id: Optional[str] = None
    page_number: Optional[int] = None
    source_type: str = ""
    text: str = ""

    def is_complete(self) -> bool:
        return bool(self.document_id and (self.chunk_id or self.asset_id))


@dataclass
class MMEvidence:
    key: str
    modality: str
    source_type: str
    content: str
    title: str = ""
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    asset_id: Optional[str] = None
    page_number: Optional[int] = None

    # Signals carried from retrieval (Module 3) + vision/OCR confidences.
    base_score: float = 0.0            # fused/reranked confidence from retrieval
    retrieval_score: float = 0.0
    rerank_score: float = 0.0
    vision_confidence: Optional[float] = None
    ocr_confidence: Optional[float] = None
    contributing_modalities: List[str] = field(default_factory=list)

    # Filled by the pipeline.
    evidence_score: float = 0.0
    ranking_contributions: Dict[str, float] = field(default_factory=dict)
    token_cost: int = 0
    compressed: bool = False
    original_tokens: int = 0
    merged_from: List[str] = field(default_factory=list)
    included: bool = False
    rank: int = 0
    selection_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def citation(self) -> MMCitation:
        return MMCitation(modality=self.modality, document_id=self.document_id, chunk_id=self.chunk_id,
                          asset_id=self.asset_id, page_number=self.page_number, source_type=self.source_type,
                          text=(self.content or "")[:200])


@dataclass
class ContextBlock:
    modality: str
    header: str
    items: List[MMEvidence]
    token_cost: int
    order: int


# --------------------------------------------------------------------- API request
class ContextBuildRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    modalities: Optional[List[str]] = None
    document_id: Optional[str] = None
    top_k: int = Field(default=20, ge=1, le=100)
    token_budget: Optional[int] = Field(default=None, ge=256, le=32000)
    compress: bool = True
    dedup: bool = True
    explain: bool = True
    developer: bool = False           # include the raw assembled prompt + per-item detail


# --------------------------------------------------------------------- API output
class CitationOut(BaseModel):
    modality: str
    document_id: Optional[str]
    chunk_id: Optional[str]
    asset_id: Optional[str]
    page_number: Optional[int]
    source_type: str
    text: str


class EvidenceOut(BaseModel):
    key: str
    modality: str
    source_type: str
    title: str
    content: str
    document_id: Optional[str]
    page_number: Optional[int]
    evidence_score: float
    token_cost: int
    compressed: bool
    rank: int
    selection_reason: str
    contributing_modalities: List[str] = []
    ranking_contributions: Optional[Dict[str, float]] = None
    merged_from: List[str] = []


class ContextBlockOut(BaseModel):
    modality: str
    header: str
    order: int
    token_cost: int
    items: List[EvidenceOut]


class BudgetAllocationOut(BaseModel):
    modality: str
    allocated: int
    used: int


class ContextMetrics(BaseModel):
    retrieved: int
    after_dedup: int
    included: int
    dropped: int
    context_tokens: int
    prompt_tokens: int
    duplicate_reduction: float
    compression_ratio: float
    total_ms: float
    stage_ms: Dict[str, float]


class ContextResponse(BaseModel):
    query: str
    primary_intent: str
    modalities: List[str]
    weights: Dict[str, float]
    blocks: List[ContextBlockOut]
    citations: List[CitationOut]
    budget: List[BudgetAllocationOut]
    metrics: ContextMetrics
    dropped: List[Dict[str, Any]] = []
    prompt: Optional[str] = None            # only when developer=True
    context: Optional[str] = None           # assembled context (without system/question)


class ObservabilityResponse(BaseModel):
    builds: int
    avg_total_ms: float
    avg_compression_ratio: float
    avg_duplicate_reduction: float
    avg_context_tokens: float
    intent_usage: Dict[str, int]
    recent: List[Dict[str, Any]]
