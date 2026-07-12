"""Agent framework DTOs (Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RunAgentRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    agent: str = "workspace_agent"
    conversation_id: Optional[str] = None
    document_id: Optional[str] = None
    allowed_tools: Optional[List[str]] = None        # restrict tools for this run
    granted_permissions: Optional[List[str]] = None  # restrict permissions for this run


class PlannerPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    document_id: Optional[str] = None


class RunAgentResponse(BaseModel):
    execution_id: str
    agent: str
    success: bool
    phase: str
    error: Optional[str] = None
    answer: str
    plan: Dict[str, Any]
    citations: List[Dict[str, Any]] = []
    tool_results: List[Dict[str, Any]] = []
    timeline: List[Dict[str, Any]] = []
    timings: Dict[str, float]
    prompt_package: Dict[str, Any]
    retry_count: int
    tool_count: int
    token_usage: int
    estimated_cost: float
    memory: Dict[str, Any] = {}


class ExecutionLogOut(BaseModel):
    id: str
    workspace_id: str
    agent: str
    query: str
    status: str
    success: bool
    cancelled: bool
    error: Optional[str]
    planner: str
    requires_tools: bool
    tool_count: int
    retry_count: int
    estimated_cost: float
    planner_ms: float
    tools_ms: float
    llm_ms: float
    total_ms: float
    token_usage: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecutionDetail(ExecutionLogOut):
    graph: Optional[Dict[str, Any]] = None
    timeline: Optional[List[Dict[str, Any]]] = None


class ToolSpecOut(BaseModel):
    name: str
    version: str
    description: str
    category: str
    permissions: List[str]
    parallel_safe: bool
    timeout_s: float
    cost_weight: float
    params: List[Dict[str, Any]]


class AgentDescriptorOut(BaseModel):
    name: str
    version: str
    description: str
    capabilities: List[str]
    default_tools: List[str]
    status: str
    implemented: bool
    health: str


class StatsResponse(BaseModel):
    executions: int
    successful: int
    avg_total_ms: float
