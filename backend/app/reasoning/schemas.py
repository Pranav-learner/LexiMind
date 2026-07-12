"""DTOs for the Verification & Reasoning API (Phase 6, Module 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EvidenceIn(BaseModel):
    text: str
    index: Optional[int] = None
    source_type: Optional[str] = "text"
    document_id: Optional[str] = None
    title: Optional[str] = None
    page_number: Optional[int] = None
    timespan: Optional[str] = None
    speaker_label: Optional[str] = None
    score: Optional[float] = None


class VerifyRequest(BaseModel):
    """Ad-hoc verification of an answer against supplied evidence (developer / manual)."""
    answer: str = Field(min_length=1, max_length=100_000)
    evidence: List[EvidenceIn] = []
    mode: str = Field(default="fast", pattern="^(fast|thorough)$")
    signals: Dict[str, Any] = {}
    execution_id: Optional[str] = None
    persist: bool = True


class VerifyTaskRequest(BaseModel):
    mode: str = Field(default="fast", pattern="^(fast|thorough)$")


class VerificationLogOut(BaseModel):
    id: str
    workspace_id: str
    execution_id: Optional[str]
    agent: str
    task_type: str
    mode: str
    status: str
    overall_confidence: float
    confidence_band: str
    claims_total: int
    supported: int
    weak: int
    unsupported: int
    conflicting: int
    contradictions_found: int
    citation_failures: int
    evidence_used: int
    warnings_count: int
    verification_ms: float
    review_ms: float
    cached: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class VerificationDetailOut(VerificationLogOut):
    report: Optional[Dict[str, Any]] = None


class VerificationStatsOut(BaseModel):
    verifications: int
    verified: int
    failed: int
    avg_confidence: float
