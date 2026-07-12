"""Temporal-intelligence DTOs (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class DeriveRequest(BaseModel):
    force: bool = False


class ChapterOut(BaseModel):
    id: str
    document_id: str
    chapter_index: int
    title: str
    summary: Optional[str]
    keywords: Optional[List[str]]
    start_ms: int
    end_ms: int
    source: str
    confidence: Optional[float]

    model_config = {"from_attributes": True}


class TopicOut(BaseModel):
    id: str
    document_id: str
    topic_index: int
    label: str
    keywords: Optional[List[str]]
    start_ms: int
    end_ms: int
    salience: Optional[float]
    source: str

    model_config = {"from_attributes": True}


class TimelineEventOut(BaseModel):
    id: str
    document_id: str
    event_index: int
    event_type: str
    title: str
    description: Optional[str]
    timestamp_ms: int
    start_ms: int
    end_ms: int
    speaker_id: Optional[str]
    scene_id: Optional[str]
    chapter_id: Optional[str]
    source: str
    confidence: Optional[float]

    model_config = {"from_attributes": True}


class DeriveResponse(BaseModel):
    document_id: str
    chapters: int
    topics: int
    events: int
