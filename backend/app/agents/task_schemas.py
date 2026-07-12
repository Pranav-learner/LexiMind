"""DTOs for the specialized-agent task API (Phase 6, Module 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------- requests
class _BaseTaskRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    document_ids: List[str] = []
    conversation_id: Optional[str] = None
    granted_permissions: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    verify: Optional[str] = Field(default=None, pattern="^(off|fast|thorough)$")  # M3 verification mode
    contribute_graph: Optional[bool] = None   # P7-M1: feed the answer into the knowledge graph


class ResearchRequest(_BaseTaskRequest):
    evidence_limit: Optional[int] = Field(default=None, ge=1, le=100)


class WritingRequest(_BaseTaskRequest):
    doc_type: str = "research_report"


class ComparisonTarget(BaseModel):
    label: Optional[str] = None
    document_id: Optional[str] = None
    topic: Optional[str] = None


class ComparisonRequest(_BaseTaskRequest):
    targets: Optional[List[ComparisonTarget]] = None


class StudyRequest(_BaseTaskRequest):
    deliverables: Optional[List[str]] = None
    subject: Optional[str] = None


class WorkflowRunRequest(_BaseTaskRequest):
    params: Dict[str, Any] = {}
    definition_override: Optional[Dict[str, Any]] = None


class PreviewRequest(BaseModel):
    task_type: str = Field(pattern="^(research|writing|comparison|study)$")
    objective: str = Field(min_length=1, max_length=8000)
    document_ids: List[str] = []
    params: Dict[str, Any] = {}


# --------------------------------------------------------------------- responses
class TaskLogOut(BaseModel):
    id: str
    workspace_id: str
    agent: str
    task_type: str
    objective: str
    status: str
    success: bool
    cancelled: bool
    phase: str
    error: Optional[str]
    workflow: Optional[str]
    evidence_count: int
    citation_count: int
    tool_calls: int
    documents_used: int
    media_used: int
    workspace_used: bool
    planner_ms: float
    research_ms: float
    writing_ms: float
    total_ms: float
    token_usage: int
    cost_estimate: float
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskDetailOut(TaskLogOut):
    plan: Optional[Dict[str, Any]] = None
    steps: Optional[List[Dict[str, Any]]] = None
    timeline: Optional[List[Dict[str, Any]]] = None
    output: Optional[Dict[str, Any]] = None
    knowledge_gaps: Optional[List[str]] = None
    document_ids: Optional[List[str]] = None
    params: Optional[Dict[str, Any]] = None


class TaskStatsOut(BaseModel):
    tasks: int
    successful: int
    avg_total_ms: float
    total_tokens: int


class ExportOut(BaseModel):
    task_id: str
    format: str
    content: Any
    filename: str
