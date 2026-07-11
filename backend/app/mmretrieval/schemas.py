"""Multimodal retrieval DTOs — the internal hit type + the API request/response contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# The modalities a retriever can serve.
MODALITIES = ("text", "ocr", "image", "diagram", "table", "metadata")


# --------------------------------------------------------------------- internal hit (mutable)
@dataclass
class RetrievalHit:
    """A single result flowing through the pipeline. Scores are filled in stage by stage, so the
    final object carries a COMPLETE retrieval explanation (Step 8)."""

    key: str                       # dedup key (document + chunk/asset)
    modality: str                  # which retriever produced it
    source_type: str               # text_chunk | ocr | image | diagram | table | metadata | document
    document_id: Optional[str]
    content: str
    title: str = ""
    chunk_id: Optional[str] = None
    asset_id: Optional[str] = None
    page_number: Optional[int] = None
    raw_score: float = 0.0
    normalized_score: float = 0.0
    rank_in_modality: int = 0
    fusion_score: float = 0.0
    fusion_contributions: Dict[str, float] = field(default_factory=dict)  # modality -> contribution
    reranker_score: Optional[float] = None
    final_rank: int = 0
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    contributing_modalities: List[str] = field(default_factory=list)


# --------------------------------------------------------------------- API request
class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    modalities: Optional[List[str]] = None    # override intent detection
    document_id: Optional[str] = None         # scope to one document
    top_k: int = Field(default=10, ge=1, le=50)
    per_retriever_k: int = Field(default=20, ge=1, le=100)
    fusion: str = "rrf"                        # rrf | weighted_sum
    normalize: str = "minmax"                  # minmax | zscore
    rerank: bool = True
    explain: bool = True


# --------------------------------------------------------------------- API output
class SearchResultOut(BaseModel):
    key: str
    modality: str
    source_type: str
    document_id: Optional[str]
    chunk_id: Optional[str]
    asset_id: Optional[str]
    page_number: Optional[int]
    title: str
    content: str
    confidence: float
    final_rank: int
    metadata: Dict[str, Any] = {}
    explanation: Optional[Dict[str, Any]] = None   # scores + contributions (when explain=True)


class RetrieverStat(BaseModel):
    modality: str
    count: int
    latency_ms: float


class SearchResponse(BaseModel):
    query: str
    intents: List[str]                  # activated modalities
    detected: List[str]                 # explicitly-named modalities
    primary: str
    weights: Dict[str, float]
    total: int
    total_ms: float
    fusion_ms: float
    rerank_ms: float
    retriever_stats: List[RetrieverStat]
    results: List[SearchResultOut]


class SuggestionsResponse(BaseModel):
    query: str
    suggestions: List[str]


class ModalityCount(BaseModel):
    modality: str
    count: int


class StatsResponse(BaseModel):
    searches: int
    avg_latency_ms: float
    modality_usage: Dict[str, int]
    indexed: Dict[str, int]              # counts of retrievable assets per modality
    recent_queries: List[str]


class HealthResponse(BaseModel):
    status: str
    retrievers: List[str]
    text_backend: str
    indexed: Dict[str, int]
    embedding_queue: Dict[str, int]      # pending vs embedded (future multimodal embedding)
