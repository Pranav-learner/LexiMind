"""Phase 9 · Module 3 — Integration & Automation ORM models.

All tables are additive and created dynamically on startup via ``init_db``.
No Alembic migrations are required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uuid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ----------------------------------------------------------------- Connectors


class ConnectorInstance(Base):
    """An installed connector in a workspace."""
    __tablename__ = "connector_instances"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("conn"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    connector_type: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g. 'google_drive', 'github'
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)  # storage, productivity, developer, communication
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="installed")  # installed, connected, syncing, error, disabled
    health: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")  # healthy, degraded, unhealthy, unknown
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    sync_items_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class ConnectorAuth(Base):
    """Encrypted OAuth/API credentials for a connector instance."""
    __tablename__ = "connector_auths"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("cauth"))
    connector_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    auth_type: Mapped[str] = mapped_column(String(30), nullable=False)  # oauth2, api_key, token, basic
    encrypted_credentials: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet-encrypted JSON blob
    iv: Mapped[str] = mapped_column(String(80), nullable=False, default="fernet_autogen")
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


# ----------------------------------------------------------------- Sync State


class SyncState(Base):
    """Incremental sync cursors/tokens per connector + resource type."""
    __tablename__ = "sync_states"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("ssync"))
    connector_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g. 'files', 'issues', 'messages'
    cursor: Mapped[str] = mapped_column(Text, nullable=False, default="")  # opaque sync token
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    items_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    direction: Mapped[str] = mapped_column(String(20), default="inbound", nullable=False)  # inbound, outbound, bidirectional
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


# ----------------------------------------------------------------- Event Bus


class IntegrationEvent(Base):
    """Persistent event log for the platform-wide event bus."""
    __tablename__ = "integration_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("evt"))
    workspace_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None, nullable=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True, nullable=False)  # e.g. 'connector.sync.completed'
    source: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g. 'github', 'automation', 'scheduler'
    actor_id: Mapped[str | None] = mapped_column(String(40), default=None, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


# ----------------------------------------------------------------- Webhooks


class WebhookEndpoint(Base):
    """Registered incoming/outgoing webhook endpoint."""
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("whk"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)  # incoming, outgoing
    url: Mapped[str] = mapped_column(Text, nullable=False)  # target URL (outgoing) or generated path (incoming)
    secret: Mapped[str] = mapped_column(Text, nullable=False, default="")  # HMAC signing secret (encrypted)
    event_filter: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)  # event types to trigger on
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retry_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=lambda: {"max_retries": 3, "backoff_factor": 2.0})
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class WebhookDelivery(Base):
    """Delivery attempt history for outgoing webhooks."""
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("wdel"))
    webhook_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    event_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    response_status: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending, success, failed, dead_letter
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


# ----------------------------------------------------------------- Automation


class AutomationWorkflow(Base):
    """Event-driven automation workflow definition."""
    __tablename__ = "automation_workflows"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("wf"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trigger: Mapped[dict] = mapped_column(JSON, nullable=False)  # {type: "event"|"schedule"|"webhook", pattern: "..."}
    conditions: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)  # [{field, operator, value}]
    actions: Mapped[list[dict]] = mapped_column(JSON, nullable=False)  # [{type, config}]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    template_id: Mapped[str | None] = mapped_column(String(80), default=None, nullable=True)
    execution_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class AutomationExecution(Base):
    """Workflow execution run history."""
    __tablename__ = "automation_executions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("wfrun"))
    workflow_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    trigger_event_id: Mapped[str | None] = mapped_column(String(40), default=None, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")  # running, completed, failed, cancelled
    steps_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    steps_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)


# ----------------------------------------------------------------- Scheduler


class ScheduledJob(Base):
    """Cron/one-time/recurring job definition."""
    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("job"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)  # cron, one_time, interval
    schedule: Mapped[str] = mapped_column(String(120), nullable=False, default="")  # cron expression or ISO datetime
    action: Mapped[dict] = mapped_column(JSON, nullable=False)  # {type: "sync"|"automation"|"agent", config: {...}}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_runs: Mapped[int | None] = mapped_column(Integer, default=None, nullable=True)  # None = unlimited
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


class ScheduledJobRun(Base):
    """Job execution history."""
    __tablename__ = "scheduled_job_runs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("jrun"))
    job_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")  # running, completed, failed
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)


# ----------------------------------------------------------------- MCP Servers


class MCPServerRegistration(Base):
    """Registered external MCP server."""
    __tablename__ = "mcp_server_registrations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("mcp"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    server_url: Mapped[str] = mapped_column(Text, nullable=False)
    transport: Mapped[str] = mapped_column(String(30), nullable=False, default="stdio")  # stdio, http, sse
    auth_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    discovered_tools: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered")  # registered, connected, error
    health: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime, default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now, nullable=False)


# ----------------------------------------------------------------- Execution Log


class IntegrationExecutionLog(Base):
    """Unified telemetry log for all integration operations."""
    __tablename__ = "integration_execution_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: _uuid("ilog"))
    workspace_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(40), default=None, nullable=True)
    operation: Mapped[str] = mapped_column(String(80), index=True, nullable=False)  # connector.sync, webhook.delivery, automation.run, scheduler.run, mcp.tool_call
    connector_type: Mapped[str | None] = mapped_column(String(80), default=None, nullable=True)
    connector_id: Mapped[str | None] = mapped_column(String(40), default=None, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")  # running, completed, failed
    items_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_exported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    execution_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
