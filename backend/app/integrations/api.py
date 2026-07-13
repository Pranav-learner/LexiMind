"""REST endpoints for the Integration & Automation platform."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_id
from app.db.base import get_db
from app.integrations.automation import AutomationEngine
from app.integrations.errors import IntegrationError
from app.integrations.event_bus import event_bus
from app.integrations.models import (
    AutomationExecution,
    AutomationWorkflow,
    ConnectorInstance,
    IntegrationExecutionLog,
    MCPServerRegistration,
    ScheduledJob,
    SyncState,
    WebhookEndpoint,
)
from app.integrations.schemas import (
    BrowseOut,
    BrowseRequest,
    ConnectorAuthOut,
    ConnectorAuthRequest,
    ConnectorConfigUpdate,
    ConnectorInstallRequest,
    ConnectorOut,
    ConnectorTypeOut,
    IntegrationDashboardOut,
    IntegrationEventOut,
    IntegrationLogOut,
    MCPServerOut,
    MCPServerRegisterRequest,
    MCPServerUpdateRequest,
    ScheduledJobCreateRequest,
    ScheduledJobOut,
    ScheduledJobUpdateRequest,
    SyncStatusOut,
    SyncTriggerRequest,
    WebhookCreateRequest,
    WebhookOut,
    WebhookUpdateRequest,
    WorkflowCreateRequest,
    WorkflowExecutionOut,
    WorkflowOut,
    WorkflowTemplateOut,
)
from app.integrations.sdk.auth import AuthManager
from app.integrations.sdk.registry import connector_registry
from app.integrations.sdk.runtime import ConnectorRuntime
from app.integrations.webhooks import WebhookManager
from app.workspaces.repository import WorkspaceRepository

router = APIRouter(prefix="/workspaces/{workspace_id}/integrations", tags=["integrations"])


def _verify_workspace(db: Session, workspace_id: str, owner_id: str) -> None:
    if WorkspaceRepository(db).get(workspace_id, owner_id) is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' was not found.")


def _handle(fn):
    try:
        return fn()
    except IntegrationError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ----------------------------------------------------------------- Dashboard

@router.get("/dashboard", response_model=IntegrationDashboardOut)
def get_dashboard(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    connectors = db.query(ConnectorInstance).filter(ConnectorInstance.workspace_id == workspace_id).all()
    workflows = db.query(AutomationWorkflow).filter(AutomationWorkflow.workspace_id == workspace_id).all()
    webhooks = db.query(WebhookEndpoint).filter(WebhookEndpoint.workspace_id == workspace_id).all()
    jobs = db.query(ScheduledJob).filter(ScheduledJob.workspace_id == workspace_id).all()
    mcp = db.query(MCPServerRegistration).filter(MCPServerRegistration.workspace_id == workspace_id).all()

    recent_logs = db.query(IntegrationExecutionLog).filter(
        IntegrationExecutionLog.workspace_id == workspace_id
    ).order_by(IntegrationExecutionLog.created_at.desc()).limit(10).all()

    # Stub mapping log entities
    return IntegrationDashboardOut(
        installed_connectors=len(connectors),
        healthy_connectors=len([c for c in connectors if c.health == "healthy"]),
        active_workflows=len([w for w in workflows if w.is_active]),
        total_synced_items=sum(c.sync_items_count for c in connectors),
        active_webhooks=len([wh for wh in webhooks if wh.is_active]),
        scheduled_jobs=len([j for j in jobs if j.is_active]),
        mcp_servers=len([m for m in mcp if m.is_active]),
        recent_events=[],
        recent_logs=[IntegrationLogOut.model_validate(l) for l in recent_logs],
    )


# ----------------------------------------------------------------- Connectors

@router.get("/connectors/types", response_model=List[ConnectorTypeOut])
def list_connector_types(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    types = connector_registry().all_types()
    return [
        ConnectorTypeOut(
            type=t.type,
            name=t.name,
            category=t.category,
            description=t.description,
            icon=t.icon,
            capabilities=[k for k, v in t.capabilities.__dict__.items() if v],
            auth_type=t.auth_type,
            version=t.version,
            status=t.status,
        )
        for t in types
    ]


@router.get("/connectors", response_model=List[ConnectorOut])
def list_connectors(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    connectors = db.query(ConnectorInstance).filter(ConnectorInstance.workspace_id == workspace_id).all()
    return [ConnectorOut.model_validate(c) for c in connectors]


@router.post("/connectors", response_model=ConnectorOut, status_code=201)
def install_connector(
    workspace_id: str,
    req: ConnectorInstallRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)

    # Ensure connector type exists
    meta = connector_registry().get(req.connector_type)().metadata()

    # Prevent duplicates
    existing = db.query(ConnectorInstance).filter(
        ConnectorInstance.workspace_id == workspace_id,
        ConnectorInstance.connector_type == req.connector_type,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Connector '{req.connector_type}' already installed.")

    instance = ConnectorInstance(
        workspace_id=workspace_id,
        owner_id=owner_id,
        connector_type=req.connector_type,
        display_name=req.display_name or meta.name,
        category=meta.category,
        config=req.config,
        status="installed",
        health="unknown",
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return ConnectorOut.model_validate(instance)


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
def update_connector(
    workspace_id: str,
    connector_id: str,
    req: ConnectorConfigUpdate,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    instance = db.query(ConnectorInstance).filter(
        ConnectorInstance.id == connector_id,
        ConnectorInstance.workspace_id == workspace_id,
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Connector instance not found.")

    if req.display_name is not None:
        instance.display_name = req.display_name
    if req.config is not None:
        instance.config = req.config
    if req.is_active is not None:
        instance.is_active = req.is_active

    db.commit()
    db.refresh(instance)
    return ConnectorOut.model_validate(instance)


@router.delete("/connectors/{connector_id}", status_code=204)
def delete_connector(
    workspace_id: str,
    connector_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    instance = db.query(ConnectorInstance).filter(
        ConnectorInstance.id == connector_id,
        ConnectorInstance.workspace_id == workspace_id,
    ).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Connector instance not found.")

    db.delete(instance)
    AuthManager(db).delete(connector_id)
    db.commit()
    return Response(status_code=204)


@router.post("/connectors/{connector_id}/auth", response_model=ConnectorAuthOut)
def configure_auth(
    workspace_id: str,
    connector_id: str,
    req: ConnectorAuthRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    auth = AuthManager(db).store_credentials(
        connector_id=connector_id,
        auth_type=req.auth_type,
        credentials=req.credentials,
        scopes=req.scopes,
    )
    return ConnectorAuthOut(
        connector_id=connector_id,
        auth_type=auth.auth_type,
        is_valid=auth.is_valid,
        scopes=auth.scopes,
        expires_at=auth.expires_at,
    )


@router.post("/connectors/{connector_id}/sync", response_model=SyncStatusOut)
def trigger_sync(
    workspace_id: str,
    connector_id: str,
    req: SyncTriggerRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)

    runtime = ConnectorRuntime(db, workspace_id, owner_id)
    res = _handle(lambda: runtime.execute_with_telemetry(
        connector_id=connector_id,
        operation_name="sync",
        func=lambda c: c.sync(resource_types=req.resource_types),
    ))

    instance = db.query(ConnectorInstance).filter(ConnectorInstance.id == connector_id).first()
    if instance:
        instance.last_sync_at = datetime.now()
        instance.sync_items_count += res.items_imported
        instance.status = "connected"
        instance.health = "healthy"
        db.commit()

    return SyncStatusOut(
        connector_id=connector_id,
        status="completed",
        last_sync_at=datetime.now(),
        items_synced=res.items_imported,
    )


@router.post("/connectors/{connector_id}/browse", response_model=BrowseOut)
def browse_connector(
    workspace_id: str,
    connector_id: str,
    req: BrowseRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    runtime = ConnectorRuntime(db, workspace_id, owner_id)
    res = _handle(lambda: runtime.execute_with_telemetry(
        connector_id=connector_id,
        operation_name="browse",
        func=lambda c: c.browse(path=req.path, page_size=req.page_size, cursor=req.cursor),
    ))
    return BrowseOut(
        connector_id=connector_id,
        path=req.path,
        items=[i.to_dict() for i in res.items],
        next_cursor=res.next_cursor,
        total_items=res.total_items,
    )


# ----------------------------------------------------------------- Webhooks

@router.get("/webhooks", response_model=List[WebhookOut])
def list_webhooks(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    webhooks = db.query(WebhookEndpoint).filter(WebhookEndpoint.workspace_id == workspace_id).all()
    return [WebhookOut.model_validate(w) for w in webhooks]


@router.post("/webhooks", response_model=WebhookOut, status_code=201)
def create_webhook(
    workspace_id: str,
    req: WebhookCreateRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    mgr = WebhookManager(db)
    webhook = mgr.create_endpoint(
        workspace_id=workspace_id,
        owner_id=owner_id,
        name=req.name,
        direction=req.direction,
        url=req.url,
        event_filter=req.event_filter,
        retry_policy=req.retry_policy,
    )
    return WebhookOut.model_validate(webhook)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookOut)
def update_webhook(
    workspace_id: str,
    webhook_id: str,
    req: WebhookUpdateRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    webhook = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.id == webhook_id,
        WebhookEndpoint.workspace_id == workspace_id,
    ).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found.")

    if req.name is not None:
        webhook.name = req.name
    if req.url is not None:
        webhook.url = req.url
    if req.event_filter is not None:
        webhook.event_filter = req.event_filter
    if req.is_active is not None:
        webhook.is_active = req.is_active
    if req.retry_policy is not None:
        webhook.retry_policy = req.retry_policy

    db.commit()
    db.refresh(webhook)
    return WebhookOut.model_validate(webhook)


@router.delete("/webhooks/{webhook_id}", status_code=204)
def delete_webhook(
    workspace_id: str,
    webhook_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    webhook = db.query(WebhookEndpoint).filter(
        WebhookEndpoint.id == webhook_id,
        WebhookEndpoint.workspace_id == workspace_id,
    ).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found.")
    db.delete(webhook)
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------- Automation

@router.get("/workflows", response_model=List[WorkflowOut])
def list_workflows(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    workflows = db.query(AutomationWorkflow).filter(AutomationWorkflow.workspace_id == workspace_id).all()
    return [WorkflowOut.model_validate(w) for w in workflows]


@router.post("/workflows", response_model=WorkflowOut, status_code=201)
def create_workflow(
    workspace_id: str,
    req: WorkflowCreateRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    workflow = AutomationWorkflow(
        workspace_id=workspace_id,
        owner_id=owner_id,
        name=req.name,
        description=req.description,
        trigger=req.trigger,
        conditions=req.conditions,
        actions=req.actions,
        template_id=req.template_id,
        is_active=True,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return WorkflowOut.model_validate(workflow)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
def update_workflow(
    workspace_id: str,
    workflow_id: str,
    req: WorkflowUpdateRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    wf = db.query(AutomationWorkflow).filter(
        AutomationWorkflow.id == workflow_id,
        AutomationWorkflow.workspace_id == workspace_id,
    ).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    if req.name is not None:
        wf.name = req.name
    if req.description is not None:
        wf.description = req.description
    if req.trigger is not None:
        wf.trigger = req.trigger
    if req.conditions is not None:
        wf.conditions = req.conditions
    if req.actions is not None:
        wf.actions = req.actions
    if req.is_active is not None:
        wf.is_active = req.is_active

    db.commit()
    db.refresh(wf)
    return WorkflowOut.model_validate(wf)


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete_workflow(
    workspace_id: str,
    workflow_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    wf = db.query(AutomationWorkflow).filter(
        AutomationWorkflow.id == workflow_id,
        AutomationWorkflow.workspace_id == workspace_id,
    ).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    db.delete(wf)
    db.commit()
    return Response(status_code=204)


@router.post("/workflows/{workflow_id}/run", response_model=WorkflowExecutionOut)
def trigger_workflow(
    workspace_id: str,
    workflow_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    engine = AutomationEngine(db)
    res = _handle(lambda: engine.execute_workflow(workflow_id))
    return WorkflowExecutionOut.model_validate(res)


@router.get("/workflows/templates", response_model=List[WorkflowTemplateOut])
def get_workflow_templates(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    # Pre-built automation workflow templates
    return [
        WorkflowTemplateOut(
            id="tmpl_sync_drive_notify_slack",
            name="S3/Drive Sync Notification",
            description="Trigger full sync and post notification message to communication channels.",
            category="storage",
            trigger={"type": "event", "pattern": "connector.sync.completed"},
            conditions=[],
            actions=[
                {"type": "notification", "config": {"connector_id": "", "message": "Google Drive Sync Done!"}}
            ],
            icon="⚡",
        )
    ]


# ----------------------------------------------------------------- Scheduler

@router.get("/scheduler/jobs", response_model=List[ScheduledJobOut])
def list_scheduled_jobs(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    jobs = db.query(ScheduledJob).filter(ScheduledJob.workspace_id == workspace_id).all()
    return [ScheduledJobOut.model_validate(j) for j in jobs]


@router.post("/scheduler/jobs", response_model=ScheduledJobOut, status_code=201)
def create_scheduled_job(
    workspace_id: str,
    req: ScheduledJobCreateRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)

    from app.integrations.scheduler import scheduler as sys_scheduler
    next_run = sys_scheduler.calculate_next_run(req.job_type, req.schedule, datetime.now())

    job = ScheduledJob(
        workspace_id=workspace_id,
        owner_id=owner_id,
        name=req.name,
        job_type=req.job_type,
        schedule=req.schedule,
        action=req.action,
        max_runs=req.max_runs,
        next_run_at=next_run,
        is_active=True,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return ScheduledJobOut.model_validate(job)


@router.patch("/scheduler/jobs/{job_id}", response_model=ScheduledJobOut)
def update_scheduled_job(
    workspace_id: str,
    job_id: str,
    req: ScheduledJobUpdateRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    job = db.query(ScheduledJob).filter(
        ScheduledJob.id == job_id,
        ScheduledJob.workspace_id == workspace_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")

    if req.name is not None:
        job.name = req.name
    if req.schedule is not None:
        job.schedule = req.schedule
    if req.action is not None:
        job.action = req.action
    if req.is_active is not None:
        job.is_active = req.is_active
    if req.max_runs is not None:
        job.max_runs = req.max_runs

    db.commit()
    db.refresh(job)
    return ScheduledJobOut.model_validate(job)


@router.delete("/scheduler/jobs/{job_id}", status_code=204)
def delete_scheduled_job(
    workspace_id: str,
    job_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    job = db.query(ScheduledJob).filter(
        ScheduledJob.id == job_id,
        ScheduledJob.workspace_id == workspace_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Scheduled job not found.")
    db.delete(job)
    db.commit()
    return Response(status_code=204)


# ----------------------------------------------------------------- MCP Servers

@router.get("/mcp-servers", response_model=List[MCPServerOut])
def list_mcp_servers(
    workspace_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    servers = db.query(MCPServerRegistration).filter(MCPServerRegistration.workspace_id == workspace_id).all()
    return [MCPServerOut.model_validate(s) for s in servers]


@router.post("/mcp-servers", response_model=MCPServerOut, status_code=201)
def register_mcp_server(
    workspace_id: str,
    req: MCPServerRegisterRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    server = MCPServerRegistration(
        workspace_id=workspace_id,
        owner_id=owner_id,
        name=req.name,
        server_url=req.server_url,
        transport=req.transport,
        auth_config=req.auth_config,
        status="registered",
        health="unknown",
    )
    db.add(server)
    db.commit()
    db.refresh(server)

    # Automatically query and sync tools upon registration
    try:
        from app.integrations.mcp_client import MCPClientManager
        MCPClientManager(db).sync_server_tools(server.id)
        db.refresh(server)
    except Exception as e:
        logger.error(f"Failed to sync newly registered MCP server: {e}")

    return MCPServerOut.model_validate(server)


@router.patch("/mcp-servers/{server_id}", response_model=MCPServerOut)
def update_mcp_server(
    workspace_id: str,
    server_id: str,
    req: MCPServerUpdateRequest,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    server = db.query(MCPServerRegistration).filter(
        MCPServerRegistration.id == server_id,
        MCPServerRegistration.workspace_id == workspace_id,
    ).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found.")

    if req.name is not None:
        server.name = req.name
    if req.server_url is not None:
        server.server_url = req.server_url
    if req.transport is not None:
        server.transport = req.transport
    if req.auth_config is not None:
        server.auth_config = req.auth_config
    if req.is_active is not None:
        server.is_active = req.is_active

    db.commit()
    db.refresh(server)
    return MCPServerOut.model_validate(server)


@router.post("/mcp-servers/{server_id}/sync", response_model=MCPServerOut)
def sync_mcp_server(
    workspace_id: str,
    server_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    from app.integrations.mcp_client import MCPClientManager
    mgr = MCPClientManager(db)
    _handle(lambda: mgr.sync_server_tools(server_id))
    server = db.query(MCPServerRegistration).filter(MCPServerRegistration.id == server_id).first()
    return MCPServerOut.model_validate(server)


@router.delete("/mcp-servers/{server_id}", status_code=204)
def delete_mcp_server(
    workspace_id: str,
    server_id: str,
    owner_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _verify_workspace(db, workspace_id, owner_id)
    server = db.query(MCPServerRegistration).filter(
        MCPServerRegistration.id == server_id,
        MCPServerRegistration.workspace_id == workspace_id,
    ).first()
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found.")
    db.delete(server)
    db.commit()
    return Response(status_code=204)
