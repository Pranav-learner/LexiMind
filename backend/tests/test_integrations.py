"""Unit and integration tests for the External Integrations & Automation Platform."""

from __future__ import annotations

import hmac
import hashlib
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.base import init_db
from app.integrations.models import (
    AutomationWorkflow,
    ConnectorInstance,
    MCPServerRegistration,
    ScheduledJob,
    WebhookEndpoint,
)
from app.integrations.sdk.registry import connector_registry
from app.security import rbac


@pytest.fixture(autouse=True)
def setup_rbac(db_session: Session):
    # Grant integration permissions globally for test users if conftest uses a generic user
    pass


def test_list_connector_types(workspace):
    client, headers, _, ws = workspace
    r = client.get(f"/workspaces/{ws}/integrations/connectors/types", headers=headers)
    assert r.status_code == 200
    types = r.json()
    assert len(types) > 0
    # Must contain Google Drive and other categories
    categories = {t["category"] for t in types}
    assert "storage" in categories
    assert "productivity" in categories
    assert "developer" in categories
    assert "communication" in categories


def test_connector_installation_and_lifecycle(workspace):
    client, headers, _, ws = workspace

    # 1. Install a new connector
    payload = {
        "connector_type": "google_drive",
        "display_name": "My Shared Google Drive",
        "config": {"folder_id": "drive_root_123"},
    }
    r = client.post(f"/workspaces/{ws}/integrations/connectors", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    conn = r.json()
    assert conn["connector_type"] == "google_drive"
    assert conn["display_name"] == "My Shared Google Drive"
    assert conn["is_active"] is True
    conn_id = conn["id"]

    # 2. Configure auth credentials
    auth_payload = {
        "auth_type": "oauth2",
        "credentials": {"access_token": "ya29.fake", "refresh_token": "rfr_123"},
        "scopes": ["drive.readonly"],
    }
    r = client.post(f"/workspaces/{ws}/integrations/connectors/{conn_id}/auth", json=auth_payload, headers=headers)
    assert r.status_code == 200
    assert r.json()["is_valid"] is True

    # 3. Browse folder path
    browse_payload = {
        "path": "/Research Papers",
        "page_size": 10,
    }
    r = client.post(f"/workspaces/{ws}/integrations/connectors/{conn_id}/browse", json=browse_payload, headers=headers)
    assert r.status_code == 200
    browse_res = r.json()
    assert len(browse_res["items"]) > 0
    assert browse_res["items"][0]["type"] in ("folder", "file")

    # 4. Trigger connector sync
    sync_payload = {
        "resource_types": ["files"],
    }
    r = client.post(f"/workspaces/{ws}/integrations/connectors/{conn_id}/sync", json=sync_payload, headers=headers)
    assert r.status_code == 200
    sync_res = r.json()
    assert sync_res["status"] == "completed"
    assert sync_res["items_synced"] > 0

    # 5. Disable/Update connector
    r = client.patch(f"/workspaces/{ws}/integrations/connectors/{conn_id}", json={"is_active": False}, headers=headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    # 6. Delete connector
    r = client.delete(f"/workspaces/{ws}/integrations/connectors/{conn_id}", headers=headers)
    assert r.status_code == 204


def test_webhook_endpoints_lifecycle(workspace):
    client, headers, _, ws = workspace

    # 1. Create a webhook endpoint
    payload = {
        "name": "GitHub Webhook Receiver",
        "direction": "incoming",
        "event_filter": ["github.push", "github.pull_request"],
    }
    r = client.post(f"/workspaces/{ws}/integrations/webhooks", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    wh = r.json()
    assert wh["name"] == "GitHub Webhook Receiver"
    assert wh["direction"] == "incoming"
    assert wh["secret"] is not None
    assert "/incoming/" in wh["url"]
    wh_id = wh["id"]

    # 2. Update webhook configuration
    r = client.patch(f"/workspaces/{ws}/integrations/webhooks/{wh_id}", json={"name": "GitHub Main PR Hook"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "GitHub Main PR Hook"

    # 3. Delete webhook
    r = client.delete(f"/workspaces/{ws}/integrations/webhooks/{wh_id}", headers=headers)
    assert r.status_code == 204


def test_automation_workflow_execution(workspace, db_session):
    client, headers, user_id, ws = workspace

    # Setup dummy slack connector
    slack_conn = ConnectorInstance(
        workspace_id=ws,
        owner_id=user_id,
        connector_type="slack",
        display_name="Slack Comm Channel",
        category="communication",
        config={},
        status="installed",
        health="healthy",
    )
    db_session.add(slack_conn)
    db_session.commit()
    db_session.refresh(slack_conn)

    # 1. Create automation workflow
    payload = {
        "name": "Sync Completion Slack Alert",
        "description": "Ping Slack when sync finishes",
        "trigger": {"type": "event", "pattern": "connector.sync.completed"},
        "conditions": [{"field": "payload.status", "operator": "equals", "value": "success"}],
        "actions": [
            {
                "type": "notification",
                "config": {
                    "connector_id": slack_conn.id,
                    "message": "Sync succeeded",
                }
            }
        ]
    }
    r = client.post(f"/workspaces/{ws}/integrations/workflows", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    wf = r.json()
    wf_id = wf["id"]

    # 2. Trigger workflow execution manually
    r = client.post(f"/workspaces/{ws}/integrations/workflows/{wf_id}/run", headers=headers)
    assert r.status_code == 200
    exec_res = r.json()
    assert exec_res["status"] == "completed"

    # 3. Clean up
    client.delete(f"/workspaces/{ws}/integrations/workflows/{wf_id}", headers=headers)


def test_scheduler_jobs_lifecycle(workspace):
    client, headers, _, ws = workspace

    payload = {
        "name": "Daily Sync S3",
        "job_type": "interval",
        "schedule": "86400",
        "action": {
            "type": "sync",
            "config": {"connector_id": "conn_stub_123"},
        },
        "max_runs": 10,
    }
    r = client.post(f"/workspaces/{ws}/integrations/scheduler/jobs", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["name"] == "Daily Sync S3"
    assert job["next_run_at"] is not None
    job_id = job["id"]

    # Delete job
    client.delete(f"/workspaces/{ws}/integrations/scheduler/jobs/{job_id}", headers=headers)


def test_mcp_servers_lifecycle(workspace):
    client, headers, _, ws = workspace

    # Register an MCP server
    payload = {
        "name": "Local Filesystem MCP Server",
        "server_url": "http://localhost:8000/mcp",
        "transport": "sse",
        "auth_config": {},
    }
    r = client.post(f"/workspaces/{ws}/integrations/mcp-servers", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    server = r.json()
    assert server["name"] == "Local Filesystem MCP Server"
    server_id = server["id"]

    # Delete server
    client.delete(f"/workspaces/{ws}/integrations/mcp-servers/{server_id}", headers=headers)


def test_dashboard_aggregation(workspace):
    client, headers, _, ws = workspace
    r = client.get(f"/workspaces/{ws}/integrations/dashboard", headers=headers)
    assert r.status_code == 200
    dash = r.json()
    assert "installed_connectors" in dash
    assert "healthy_connectors" in dash
