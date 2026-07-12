"""DTOs for the Multi-Agent Orchestration API (Phase 6, Module 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RunWorkflowRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    document_ids: List[str] = []
    workflow: Optional[str] = None                     # named template; omit to auto-decompose
    graph: Optional[Dict[str, Any]] = None             # custom TaskGraph.to_dict() (advanced)
    params: Dict[str, Any] = {}
    granted_permissions: Optional[List[str]] = None
    allowed_tools: Optional[List[str]] = None


class PlanRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=8000)
    document_ids: List[str] = []
    params: Dict[str, Any] = {}


class OrchestrationLogOut(BaseModel):
    id: str
    workspace_id: str
    objective: str
    workflow: str
    planner: str
    status: str
    node_count: int
    parallel_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    recovered_tasks: int
    retries: int
    llm_calls: int
    token_usage: int
    cost_estimate: float
    planner_ms: float
    schedule_ms: float
    aggregate_ms: float
    total_ms: float
    verification_status: str
    verification_confidence: float
    agents_used: Optional[List[str]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrchestrationDetailOut(OrchestrationLogOut):
    graph: Optional[Dict[str, Any]] = None
    messages: Optional[List[Dict[str, Any]]] = None
    node_results: Optional[List[Dict[str, Any]]] = None
    output: Optional[Dict[str, Any]] = None
    final_verification: Optional[Dict[str, Any]] = None


class OrchestrationStatsOut(BaseModel):
    orchestrations: int
    completed: int
    avg_total_ms: float
