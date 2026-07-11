"""Flashcard/Deck/Review DTOs + list query enums (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- deck inputs
class DeckCreate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    color: Optional[str] = None
    icon: Optional[str] = None


class DeckUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    color: Optional[str] = None
    icon: Optional[str] = None
    is_archived: Optional[bool] = None


class DeckGenerate(BaseModel):
    """AI-generate a deck (async). Reuses the retrieval→context→LLM pipeline."""

    name: Optional[str] = Field(default=None, max_length=200)
    scope: Optional[str] = None                # inferred from document ids if omitted
    document_id: Optional[str] = None
    document_ids: Optional[List[str]] = None
    note_id: Optional[str] = None              # provenance back-links (source of the request)
    summary_id: Optional[str] = None
    conversation_id: Optional[str] = None
    subject: Optional[str] = None              # focus hint / seed text (e.g. a PDF selection)
    card_type_pref: Optional[str] = None       # mixed | basic | definition | cloze | truefalse
    count: Optional[int] = None                # target number of cards
    deck_id: Optional[str] = None              # append into an existing deck instead of a new one


# --------------------------------------------------------------------- card inputs
class CardCitationIn(BaseModel):
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None
    page_number: Optional[int] = None
    citation_text: str = ""
    confidence: Optional[float] = None


class CardCreate(BaseModel):
    deck_id: Optional[str] = None              # a default deck is used/created if omitted
    front: str
    back: Optional[str] = None
    hint: Optional[str] = None
    card_type: Optional[str] = None            # basic|definition|cloze|truefalse
    difficulty: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    document_id: Optional[str] = None
    note_id: Optional[str] = None
    summary_id: Optional[str] = None
    conversation_id: Optional[str] = None
    citations: Optional[List[CardCitationIn]] = None


class CardUpdate(BaseModel):
    front: Optional[str] = None
    back: Optional[str] = None
    hint: Optional[str] = None
    card_type: Optional[str] = None
    difficulty: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    is_favorite: Optional[bool] = None
    deck_id: Optional[str] = None              # move to another deck


class ReviewSubmit(BaseModel):
    rating: str                                # again | hard | good | easy
    response_time_ms: Optional[int] = Field(default=0, ge=0)


# --------------------------------------------------------------------- output DTOs
class FlashcardCitationOut(BaseModel):
    id: str
    document_id: Optional[str]
    chunk_id: Optional[str]
    page_number: Optional[int]
    workspace_id: str
    citation_text: str
    confidence: Optional[float]

    model_config = {"from_attributes": True}


class FlashcardOut(BaseModel):
    id: str
    workspace_id: str
    owner_id: str
    deck_id: str
    document_id: Optional[str]
    note_id: Optional[str]
    summary_id: Optional[str]
    conversation_id: Optional[str]
    front: str
    back: str
    hint: str
    card_type: str
    extra: Optional[Dict[str, Any]]
    difficulty: str
    created_by: str
    status: str
    is_favorite: bool
    learning_stage: str
    ease_factor: float
    interval_days: int
    repetitions: int
    review_count: int
    lapse_count: int
    correct_count: int
    mastery_score: float
    citation_count: int
    last_reviewed_at: Optional[datetime]
    next_review_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FlashcardDetail(FlashcardOut):
    citations: List[FlashcardCitationOut] = []


class DeckOut(BaseModel):
    id: str
    workspace_id: str
    owner_id: str
    name: str
    description: str
    color: str
    icon: str
    scope: str
    document_id: Optional[str]
    note_id: Optional[str]
    summary_id: Optional[str]
    conversation_id: Optional[str]
    subject: Optional[str]
    card_type_pref: str
    status: str
    progress: int
    stage: str
    error: Optional[str]
    created_by: str
    card_count: int
    is_archived: bool
    is_public: bool
    model_name: str
    generation_ms: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DeckStats(BaseModel):
    """Per-deck learning progress (computed, not stored)."""

    total: int
    new: int
    due: int
    learning: int
    review: int
    suspended: int
    mastered: int
    avg_mastery: float


class DeckWithStats(DeckOut):
    stats: Optional[DeckStats] = None


class DeckListResponse(BaseModel):
    items: List[DeckWithStats]
    total: int
    page: int
    page_size: int
    pages: int


class FlashcardListResponse(BaseModel):
    items: List[FlashcardOut]
    total: int
    page: int
    page_size: int
    pages: int


class ReviewButton(BaseModel):
    rating: str
    interval_days: int
    label: str


class ReviewCard(BaseModel):
    """A card served into a review session, with the interval each button would schedule."""

    card: FlashcardDetail
    buttons: List[ReviewButton]


class ReviewQueue(BaseModel):
    deck_id: Optional[str]
    total_due: int
    new_count: int
    due_count: int
    cards: List[ReviewCard]


class ReviewResult(BaseModel):
    card: FlashcardOut
    rating: str
    scheduled_interval: int
    next_review_at: Optional[datetime]
    mastery_score: float


class DailyActivity(BaseModel):
    date: str          # YYYY-MM-DD
    reviews: int
    correct: int


class LearningAnalytics(BaseModel):
    total_cards: int
    active_cards: int
    new_cards: int
    due_today: int
    mastered_cards: int
    suspended_cards: int
    reviews_today: int
    reviews_total: int
    accuracy: float                 # correct / reviewed (all-time), 0..1
    retention: float                # accuracy on review-stage cards only (true retention), 0..1
    avg_response_time_ms: int
    study_streak_days: int
    avg_mastery: float
    daily_activity: List[DailyActivity]
    deck_count: int


# --------------------------------------------------------------------- list query enums
class DeckSortField(str, Enum):
    created_at = "created_at"
    updated_at = "updated_at"
    name = "name"
    card_count = "card_count"


class CardSortField(str, Enum):
    created_at = "created_at"
    updated_at = "updated_at"
    next_review_at = "next_review_at"
    mastery_score = "mastery_score"
    difficulty = "difficulty"


class SortOrder(str, Enum):
    asc = "asc"
    desc = "desc"


class CardStatusFilter(str, Enum):
    any = "any"
    active = "active"
    suspended = "suspended"
    archived = "archived"


class ArchivedFilter(str, Enum):
    active = "active"
    archived = "archived"
    all = "all"


class ReviewScope(str, Enum):
    deck = "deck"
    workspace = "workspace"


CardCreate.model_rebuild()
