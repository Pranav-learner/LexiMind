"""DTOs for the AI Observability & Monitoring API (Phase 8, Module 2)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TracedQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    hops: int = Field(default=2, ge=1, le=4)


class CreateRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    metric: str = Field(min_length=1, max_length=60)
    comparator: str = Field(default="gt", pattern="^(gt|lt)$")
    threshold: float
    severity: str = Field(default="warning", pattern="^(info|warning|critical)$")
