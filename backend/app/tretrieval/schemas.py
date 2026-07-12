"""Temporal retrieval DTOs — the internal hit type + API request/response contracts.

`TemporalHit` is the temporal analogue of `mmretrieval.RetrievalHit`: it flows through the pipeline
accumulating scores stage by stage AND preserves the exact temporal provenance (Step 8) — start/end
timestamps, speaker, scene, chapter, topic — so every result (and every citation built from it)
references a precise moment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# The temporal "modalities" a retriever can serve.
TEMPORAL_MODALITIES = (
    "transcript", "speaker", "chapter", "topic", "event", "scene", "frame", "subtitle", "timestamp",
)


# --------------------------------------------------------------------- internal hit (mutable)
@dataclass
class TemporalHit:
    key: str                        # dedup key
    modality: str                   # which temporal retriever produced it
    source_type: str                # transcript_segment | speaker | chapter | topic | event | scene | frame | subtitle
    document_id: Optional[str]
    content: str
    title: str = ""

    # temporal provenance (ALWAYS preserved)
    start_ms: int = 0
    end_ms: int = 0
    speaker_id: Optional[str] = None
    speaker_label: str = ""
    scene_id: Optional[str] = None
    chapter_id: Optional[str] = None
    topic_id: Optional[str] = None
    frame_id: Optional[str] = None
    asset_id: Optional[str] = None

    # scores (filled stage by stage → a complete retrieval explanation)
    raw_score: float = 0.0
    normalized_score: float = 0.0
    rank_in_modality: int = 0
    fusion_score: float = 0.0
    fusion_contributions: Dict[str, float] = field(default_factory=dict)
    proximity_bonus: float = 0.0
    reranker_score: Optional[float] = None
    final_rank: int = 0
    confidence: float = 0.0
    contributing_modalities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------- API request
class TemporalSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    modalities: Optional[List[str]] = None      # override intent detection
    document_id: Optional[str] = None           # scope to one recording
    top_k: int = Field(default=10, ge=1, le=50)
    per_retriever_k: int = Field(default=20, ge=1, le=100)
    fusion: str = "rrf"                          # rrf | weighted_sum
    normalize: str = "minmax"                    # minmax | zscore
    rerank: bool = True
    build_context: bool = True                  # assemble timeline-aware context + prompt
    explain: bool = True


# --------------------------------------------------------------------- API output
class TemporalResultOut(BaseModel):
    key: str
    modality: str
    source_type: str
    document_id: Optional[str]
    title: str
    content: str
    start_ms: int
    end_ms: int
    timespan: str                                # human "mm:ss–mm:ss"
    speaker_id: Optional[str]
    speaker_label: str
    scene_id: Optional[str]
    chapter_id: Optional[str]
    frame_id: Optional[str]
    confidence: float
    final_rank: int
    metadata: Dict[str, Any] = {}
    explanation: Optional[Dict[str, Any]] = None


class TemporalCitationOut(BaseModel):
    index: int
    document_id: Optional[str]
    modality: str
    start_ms: int
    end_ms: int
    timespan: str
    speaker_label: str
    scene_id: Optional[str]
    frame_id: Optional[str]
    text: str


class RetrieverStat(BaseModel):
    modality: str
    count: int
    latency_ms: float


class TemporalSearchResponse(BaseModel):
    query: str
    intents: List[str]
    detected: List[str]
    primary: str
    weights: Dict[str, float]
    time_filter: Optional[Dict[str, int]] = None   # {"start_ms","end_ms"} if a timestamp was parsed
    total: int
    total_ms: float
    analysis_ms: float
    fusion_ms: float
    rerank_ms: float
    context_ms: float
    prompt_ms: float
    retriever_stats: List[RetrieverStat]
    results: List[TemporalResultOut]
    citations: List[TemporalCitationOut] = []
    prompt: Optional[str] = None                   # timeline-aware prompt (when build_context)
    context_blocks: Optional[List[Dict[str, Any]]] = None


class PromptPreviewResponse(BaseModel):
    query: str
    query_type: str
    prompt: str
    system_prompt: str
    citations: List[TemporalCitationOut] = []
    token_estimate: int


class ExplainResponse(BaseModel):
    query: str
    analysis: Dict[str, Any]
    results: List[TemporalResultOut]


class TemporalStatsResponse(BaseModel):
    searches: int
    avg_latency_ms: float
    modality_usage: Dict[str, int]
    indexed: Dict[str, int]
    recent_queries: List[str]


class TemporalHealthResponse(BaseModel):
    status: str
    retrievers: List[str]
    indexed: Dict[str, int]
