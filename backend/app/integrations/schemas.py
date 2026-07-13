"""Pydantic request/response schemas for integration REST APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ----------------------------------------------------------------- Connectors

class ConnectorTypeOut(BaseModel):
    """Available connector type from the marketplace."""
    type: str
    name: str
    category: str
    description: str
    icon: str
    capabilities: list[str]
    auth_type: str
    version: str
    status: str  # available, coming_soon


class ConnectorInstallRequest(BaseModel):
    connector_type: str
    display_name: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorConfigUpdate(BaseModel):
    display_name: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class ConnectorOut(BaseModel):
    id: str
    workspace_id: str
    connector_type: str
    display_name: str
    category: str
    config: dict[str, Any]
    status: str
    health: str
    last_sync_at: datetime | None = None
    sync_items_count: int = 0
    error_message: str | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ConnectorAuthRequest(BaseModel):
    auth_type: str = "oauth2"
    credentials: dict[str, Any] = Field(default_factory=dict)
    scopes: list[str] = Field(default_factory=list)


class ConnectorAuthOut(BaseModel):
    connector_id: str
    auth_type: str
    is_valid: bool
    scopes: list[str]
    expires_at: datetime | None = None


class SyncTriggerRequest(BaseModel):
    resource_types: list[str] = Field(default_factory=list)  # empty = all
    full_sync: bool = False


class SyncStatusOut(BaseModel):
    connector_id: str
    status: str
    last_sync_at: datetime | None = None
    items_synced: int = 0
    resources: list[dict[str, Any]] = Field(default_factory=list)


class BrowseRequest(BaseModel):
    path: str = "/"
    page_size: int = 50
    cursor: str = ""


class BrowseOut(BaseModel):
    connector_id: str
    path: str
    items: list[dict[str, Any]]
    next_cursor: str = ""
    total_items: int = 0


# ----------------------------------------------------------------- Webhooks

class WebhookCreateRequest(BaseModel):
    name: str
    direction: str = "outgoing"  # incoming, outgoing
    url: str = ""
    event_filter: list[str] = Field(default_factory=list)
    retry_policy: dict[str, Any] = Field(default_factory=lambda: {"max_retries": 3, "backoff_factor": 2.0})


class WebhookUpdateRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    event_filter: list[str] | None = None
    is_active: bool | None = None
    retry_policy: dict[str, Any] | None = None


class WebhookOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    direction: str
    url: str
    secret: str | None = None
    event_filter: list[str]
    is_active: bool
    retry_policy: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookDeliveryOut(BaseModel):
    id: str
    webhook_id: str
    event_id: str
    status: str
    attempt: int
    response_status: int | None = None
    error: str | None = None
    delivered_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ----------------------------------------------------------------- Automation

class WorkflowCreateRequest(BaseModel):
    name: str
    description: str = ""
    trigger: dict[str, Any]  # {type, pattern/schedule}
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]]
    template_id: str | None = None


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger: dict[str, Any] | None = None
    conditions: list[dict[str, Any]] | None = None
    actions: list[dict[str, Any]] | None = None
    is_active: bool | None = None


class WorkflowOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    is_active: bool
    template_id: str | None = None
    execution_count: int = 0
    last_executed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowExecutionOut(BaseModel):
    id: str
    workflow_id: str
    workspace_id: str
    status: str
    steps_completed: int
    steps_total: int
    result: dict[str, Any]
    error: str | None = None
    duration_ms: float
    started_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class WorkflowTemplateOut(BaseModel):
    id: str
    name: str
    description: str
    category: str
    trigger: dict[str, Any]
    conditions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    icon: str = "⚡"


# ----------------------------------------------------------------- Scheduler

class ScheduledJobCreateRequest(BaseModel):
    name: str
    job_type: str = "cron"  # cron, one_time, interval
    schedule: str = ""
    action: dict[str, Any] = Field(default_factory=dict)
    max_runs: int | None = None


class ScheduledJobUpdateRequest(BaseModel):
    name: str | None = None
    schedule: str | None = None
    action: dict[str, Any] | None = None
    is_active: bool | None = None
    max_runs: int | None = None


class ScheduledJobOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    job_type: str
    schedule: str
    action: dict[str, Any]
    is_active: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    run_count: int = 0
    max_runs: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScheduledJobRunOut(BaseModel):
    id: str
    job_id: str
    status: str
    result: dict[str, Any]
    error: str | None = None
    duration_ms: float
    started_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


# ----------------------------------------------------------------- MCP

class MCPServerRegisterRequest(BaseModel):
    name: str
    server_url: str
    transport: str = "stdio"
    auth_config: dict[str, Any] = Field(default_factory=dict)


class MCPServerUpdateRequest(BaseModel):
    name: str | None = None
    server_url: str | None = None
    transport: str | None = None
    auth_config: dict[str, Any] | None = None
    is_active: bool | None = None


class MCPServerOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    server_url: str
    transport: str
    discovered_tools: list[dict[str, Any]]
    status: str
    health: str
    is_active: bool
    last_health_check: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ----------------------------------------------------------------- Events & Logs

class IntegrationEventOut(BaseModel):
    id: str
    workspace_id: str | None = None
    event_type: str
    source: str
    actor_id: str | None = None
    payload: dict[str, Any]
    processed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class IntegrationLogOut(BaseModel):
    id: str
    workspace_id: str
    operation: str
    connector_type: str | None = None
    connector_id: str | None = None
    status: str
    items_imported: int
    items_exported: int
    duration_ms: float
    retries: int
    error: str | None = None
    metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


# ----------------------------------------------------------------- Dashboard

class IntegrationDashboardOut(BaseModel):
    installed_connectors: int = 0
    healthy_connectors: int = 0
    active_workflows: int = 0
    total_synced_items: int = 0
    active_webhooks: int = 0
    scheduled_jobs: int = 0
    mcp_servers: int = 0
    recent_events: list[IntegrationEventOut] = Field(default_factory=list)
    recent_logs: list[IntegrationLogOut] = Field(default_factory=list)
