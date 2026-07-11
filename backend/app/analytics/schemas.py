"""Analytics / dashboard DTOs — the visualization contract.

Aggregators emit JSON-safe dicts (so they cache cleanly); these Pydantic models document and, where
useful, validate the shape the frontend consumes. The composite dashboard returns a dict of these
sections keyed by widget name.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# --------------------------------------------------------------------- knowledge
class LanguageCount(BaseModel):
    language: str
    count: int


class RecentUpload(BaseModel):
    id: str
    display_name: str
    created_at: Optional[str]
    page_count: int
    processing_status: str


class KnowledgeStats(BaseModel):
    workspace_name: str
    documents: int
    archived_documents: int
    pages: int
    chunks: int
    embeddings: int
    words: int
    storage_bytes: int
    indexed_files: int
    ready_files: int
    avg_document_bytes: int
    embedding_model: str
    languages: List[LanguageCount]
    topics: List[str]
    recent_uploads: List[RecentUpload]
    index_health: str
    retrieval_health: str
    context_engine_health: str


# --------------------------------------------------------------------- ai usage
class ModelUsage(BaseModel):
    model: str
    count: int


class AiUsage(BaseModel):
    questions_asked: int
    conversations: int
    messages: int
    summaries_generated: int
    notes_generated: int
    flashcards_generated: int
    citation_usage: int
    avg_response_time_ms: int
    avg_retrieval_ms: int
    avg_context_size: int
    avg_token_usage: int
    estimated_cost_usd: float
    model_usage: List[ModelUsage]


# --------------------------------------------------------------------- learning
class LearningStats(BaseModel):
    study_streak_days: int
    cards_reviewed: int
    reviews_today: int
    retention: float
    accuracy: float
    avg_mastery: float
    mastered_cards: int
    due_today: int
    new_cards: int
    notes_created: int
    summaries_created: int
    documents_completed: int
    reading_minutes: int
    daily_activity: List[Dict[str, Any]]


# --------------------------------------------------------------------- documents
class DocumentAnalytics(BaseModel):
    id: str
    display_name: str
    vector_document_id: str
    pages: int
    chunks: int
    embeddings: int
    words: int
    file_size: int
    language: str
    citation_count: int
    retrieval_frequency: int
    question_frequency: int
    summaries: int
    notes: int
    flashcards: int
    reading_page: int
    reading_progress: float
    completed: bool
    last_opened: Optional[str]
    top_pages: List[Dict[str, int]]
    created_at: Optional[str]


# --------------------------------------------------------------------- retrieval
class RetrievalAnalytics(BaseModel):
    hybrid_enabled: bool
    dense_enabled: bool
    bm25_enabled: bool
    rrf_enabled: bool
    reranker_enabled: bool
    compression_enabled: bool
    dense_top_k: int
    sparse_top_k: int
    final_top_k: int
    rrf_k: int
    dedup_threshold: float
    context_window: int
    embedding_model: str
    avg_retrieval_ms: int
    avg_context_size: int
    context_utilization: float
    retrieved_answers: int
    note: str


# --------------------------------------------------------------------- activity + insights
class ActivityEvent(BaseModel):
    type: str
    title: str
    timestamp: Optional[str]
    icon: str
    target_id: Optional[str] = None
    route: Optional[str] = None


class Insight(BaseModel):
    id: str
    kind: str            # streak | review | coverage | milestone | warning | tip
    severity: str        # positive | info | warning
    icon: str
    title: str
    message: str
    action_label: Optional[str] = None
    action_route: Optional[str] = None


class ChartSeries(BaseModel):
    key: str
    label: str
    kind: str            # line | bar | donut | heatmap
    points: List[Dict[str, Any]]
