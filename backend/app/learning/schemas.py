"""DTOs for the Continuous Learning & Feedback API (Phase 8, Module 4)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    target_type: str = Field(default="answer",
                             pattern="^(answer|citation|retrieval|agent|graph|media|workspace)$")
    target_id: str = Field(default="", max_length=80)
    kind: str = Field(default="thumbs_up",
                      pattern="^(thumbs_up|thumbs_down|star|text|correction|citation)$")
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    comment: str = Field(default="", max_length=4000)
    correction: str = Field(default="", max_length=8000)
    signals: Dict[str, Any] = Field(default_factory=dict)


class ReviewRequest(BaseModel):
    note: str = Field(default="", max_length=2000)


class BuildDatasetRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
