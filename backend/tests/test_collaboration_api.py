"""Phase 9 · Module 1 — Collaboration API integration tests.

Tests the collaboration endpoints end-to-end via FastAPI TestClient:
- Organization CRUD + Org Members
- Workspace Sharing + Invitations
- Commenting
- Activity Feed
- Version Snapshots
- Presence updates
- Sync polling
- Workspace cloning / ownership transfer
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def auth_bob(client: TestClient) -> tuple[dict, str]:
    """Register Bob and return headers and user_id."""
    resp = client.post(
        "/auth/register",
        json={"email": "bob@example.com", "password": "supersecret2", "display_name": "Bob"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return headers, body["user"]["id"]


@pytest.fixture
def auth_charlie(client: TestClient) -> tuple[dict, str]:
    """Register Charlie and return headers and user_id."""
    resp = client.post(
        "/auth/register",
        json={"email": "charlie@example.com", "password": "supersecret3", "display_name": "Charlie"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return headers, body["user"]["id"]


# ════════════════════════════════════════════════════════════════════════
#  1. Organization API tests
# ════════════════════════════════════════════════════════════════════════


def test_org_api_crud(client: TestClient, auth):
    _, alice_headers, _ = auth

    # Create Org.
    resp = client.post(
        "/collaboration/organizations",
        json={"name": "Acme Corp", "description": "Doing Acme things"},
        headers=alice_headers,
    )
    assert resp.status_code == 201, resp.text
    org = resp.json()
    assert org["name"] == "Acme Corp"
    assert org["slug"] == "acme-corp"

    # List Orgs.
    resp = client.get("/collaboration/organizations", headers=alice_headers)
    assert resp.status_code == 200
    orgs = resp.json()
    assert len(orgs) == 1
    assert orgs[0]["id"] == org["id"]

    # Get Org.
    resp = client.get(f"/collaboration/organizations/{org['id']}", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Acme Corp"

    # Update Org.
    resp = client.patch(
        f"/collaboration/organizations/{org['id']}",
        json={"name": "Acme Global"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Acme Global"

    # Delete Org.
    resp = client.delete(f"/collaboration/organizations/{org['id']}", headers=alice_headers)
    assert resp.status_code == 204


def test_org_members_api(client: TestClient, auth, auth_bob):
    _, alice_headers, _ = auth
    bob_headers, bob_id = auth_bob

    # Alice creates org.
    resp = client.post(
        "/collaboration/organizations",
        json={"name": "Wayne Enterprises"},
        headers=alice_headers,
    )
    org = resp.json()

    # Alice adds Bob.
    resp = client.post(
        f"/collaboration/organizations/{org['id']}/members",
        json={"user_id": bob_id, "role": "admin"},
        headers=alice_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["user_id"] == bob_id

    # List Org Members.
    resp = client.get(f"/collaboration/organizations/{org['id']}/members", headers=alice_headers)
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 2  # Alice and Bob

    # Remove Bob.
    resp = client.delete(
        f"/collaboration/organizations/{org['id']}/members/{bob_id}",
        headers=alice_headers,
    )
    assert resp.status_code == 204


# ════════════════════════════════════════════════════════════════════════
#  2. Workspace Members & Invitations API tests
# ════════════════════════════════════════════════════════════════════════


def test_workspace_collaboration_flow(client: TestClient, workspace, auth_bob):
    _, alice_headers, alice_id, ws_id = workspace
    bob_headers, bob_id = auth_bob

    # Non-member (Bob) cannot read workspace access yet.
    resp = client.get(f"/collaboration/workspaces/{ws_id}/access", headers=bob_headers)
    assert resp.status_code == 200
    assert not resp.json()["has_access"]

    # Alice invites Bob.
    resp = client.post(
        f"/collaboration/workspaces/{ws_id}/invitations",
        json={"email": "bob@example.com", "role": "editor"},
        headers=alice_headers,
    )
    assert resp.status_code == 201
    inv = resp.json()
    assert inv["invitee_email"] == "bob@example.com"
    assert inv["status"] == "pending"

    # Bob accepts invitation.
    resp = client.post(f"/collaboration/invitations/{inv['token']}/accept", headers=bob_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    # Bob should now have editor access.
    resp = client.get(f"/collaboration/workspaces/{ws_id}/access", headers=bob_headers)
    assert resp.status_code == 200
    assert resp.json()["has_access"]
    assert resp.json()["role"] == "editor"

    # List members.
    resp = client.get(f"/collaboration/workspaces/{ws_id}/members", headers=alice_headers)
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["user_id"] == bob_id
    assert members[0]["role"] == "editor"

    # Change Bob's role to viewer.
    resp = client.patch(
        f"/collaboration/workspaces/{ws_id}/members/{bob_id}",
        json={"role": "viewer"},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"

    # Remove Bob.
    resp = client.delete(f"/collaboration/workspaces/{ws_id}/members/{bob_id}", headers=alice_headers)
    assert resp.status_code == 204

    # Verify Bob no longer has access.
    resp = client.get(f"/collaboration/workspaces/{ws_id}/access", headers=bob_headers)
    assert resp.status_code == 200
    assert not resp.json()["has_access"]


# ════════════════════════════════════════════════════════════════════════
#  3. Comments API tests
# ════════════════════════════════════════════════════════════════════════


def test_commenting_api(client: TestClient, workspace, auth_bob):
    _, alice_headers, alice_id, ws_id = workspace
    bob_headers, bob_id = auth_bob

    # Make Bob member first.
    client.post(
        f"/collaboration/workspaces/{ws_id}/members",
        json={"user_id": bob_id, "role": "editor"},
        headers=alice_headers,
    )

    # Bob comments.
    resp = client.post(
        f"/collaboration/workspaces/{ws_id}/comments",
        json={"target_type": "document", "target_id": "doc_xyz", "content": "I like this doc."},
        headers=bob_headers,
    )
    assert resp.status_code == 201
    cmt = resp.json()
    assert cmt["content"] == "I like this doc."
    assert cmt["author_id"] == bob_id

    # Reply to comment.
    resp = client.post(
        f"/collaboration/workspaces/{ws_id}/comments",
        json={
            "target_type": "document", "target_id": "doc_xyz",
            "content": "Me too.", "parent_comment_id": cmt["id"],
        },
        headers=alice_headers,
    )
    assert resp.status_code == 201
    reply = resp.json()
    assert reply["parent_comment_id"] == cmt["id"]

    # List comments filterable by target.
    resp = client.get(
        f"/collaboration/workspaces/{ws_id}/comments?target_type=document&target_id=doc_xyz",
        headers=alice_headers,
    )
    assert resp.status_code == 200
    comments = resp.json()
    assert len(comments) == 2

    # Edit.
    resp = client.patch(
        f"/collaboration/collaboration/comments/{cmt['id']}",
        json={"content": "Actually, it's just okay."},
        headers=bob_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "Actually, it's just okay."

    # Resolve.
    resp = client.post(f"/collaboration/collaboration/comments/{cmt['id']}/resolve", headers=alice_headers)
    assert resp.status_code == 200
    assert resp.json()["is_resolved"]

    # Delete.
    resp = client.delete(f"/collaboration/collaboration/comments/{cmt['id']}", headers=bob_headers)
    assert resp.status_code == 204


# ════════════════════════════════════════════════════════════════════════
#  4. Activity Feed API tests
# ════════════════════════════════════════════════════════════════════════


def test_activity_feed_api(client: TestClient, workspace, auth_bob):
    _, alice_headers, alice_id, ws_id = workspace
    bob_headers, bob_id = auth_bob

    # Make Bob a member -> triggers member_added activity.
    client.post(
        f"/collaboration/workspaces/{ws_id}/members",
        json={"user_id": bob_id, "role": "editor"},
        headers=alice_headers,
    )

    # Bob comments -> triggers comment_added activity.
    client.post(
        f"/collaboration/workspaces/{ws_id}/comments",
        json={"target_type": "document", "target_id": "doc_x", "content": "hello"},
        headers=bob_headers,
    )

    # Fetch Activity Feed.
    resp = client.get(f"/collaboration/workspaces/{ws_id}/activity", headers=alice_headers)
    assert resp.status_code == 200
    feed = resp.json()
    assert len(feed) >= 2
    types = [event["event_type"] for event in feed]
    assert "member_added" in types
    assert "comment_added" in types


# ════════════════════════════════════════════════════════════════════════
#  5. Version Snapshots API tests
# ════════════════════════════════════════════════════════════════════════


def test_version_snapshots_api(client: TestClient, workspace):
    _, alice_headers, _, ws_id = workspace

    # Since version snapshotting is typically called internally inside a service,
    # let's assert the listing endpoint is correct (initially empty).
    resp = client.get(f"/collaboration/workspaces/{ws_id}/versions", headers=alice_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 0


# ════════════════════════════════════════════════════════════════════════
#  6. Presence API tests
# ════════════════════════════════════════════════════════════════════════


def test_presence_api(client: TestClient, workspace, auth_bob):
    _, alice_headers, alice_id, ws_id = workspace
    bob_headers, bob_id = auth_bob

    # Make Bob a member first.
    client.post(
        f"/collaboration/workspaces/{ws_id}/members",
        json={"user_id": bob_id, "role": "editor"},
        headers=alice_headers,
    )

    # Alice sends heartbeat.
    resp = client.post(
        f"/collaboration/workspaces/{ws_id}/presence/heartbeat",
        json={"active_document_id": "doc_1", "status": "online"},
        headers=alice_headers,
    )
    assert resp.status_code == 204

    # Bob sends heartbeat.
    resp = client.post(
        f"/collaboration/workspaces/{ws_id}/presence/heartbeat",
        json={"active_document_id": "doc_2", "status": "busy"},
        headers=bob_headers,
    )
    assert resp.status_code == 204

    # Fetch presence list.
    resp = client.get(f"/collaboration/workspaces/{ws_id}/presence", headers=alice_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_online"] == 2
    users_online = {m["user_id"]: m for m in data["members"]}
    assert alice_id in users_online
    assert bob_id in users_online
    assert users_online[alice_id]["active_document_id"] == "doc_1"
    assert users_online[bob_id]["active_document_id"] == "doc_2"
    assert users_online[bob_id]["status"] == "busy"


# ════════════════════════════════════════════════════════════════════════
#  7. Sync (Long-Poll) API tests
# ════════════════════════════════════════════════════════════════════════


def test_sync_poll_api(client: TestClient, workspace):
    _, alice_headers, _, ws_id = workspace

    # Polling immediately should time out and return empty list.
    # We set timeout=1 to keep tests fast.
    resp = client.get(f"/collaboration/workspaces/{ws_id}/sync?timeout=1", headers=alice_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["events"]) == 0
    cursor = data["cursor"]

    # Now let's trigger an action that publishes a sync event (like adding a comment).
    resp_cmt = client.post(
        f"/collaboration/workspaces/{ws_id}/comments",
        json={"target_type": "note", "target_id": "note_123", "content": "sync comment"},
        headers=alice_headers,
    )
    assert resp_cmt.status_code == 201

    # Poll again with the previous cursor. It should return the comment event immediately.
    resp = client.get(f"/collaboration/workspaces/{ws_id}/sync?cursor={cursor}&timeout=1", headers=alice_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["events"]) == 1
    assert data["events"][0]["event_type"] == "comment"
    assert data["events"][0]["target_id"] == "note_123"
    assert data["cursor"] != cursor


# ════════════════════════════════════════════════════════════════════════
#  8. Workspace cloning & ownership transfer API tests
# ════════════════════════════════════════════════════════════════════════


def test_workspace_clone_and_transfer(client: TestClient, workspace, auth_bob):
    _, alice_headers, alice_id, ws_id = workspace
    bob_headers, bob_id = auth_bob

    # Clone workspace.
    resp = client.post(
        f"/collaboration/workspaces/{ws_id}/clone",
        json={"name": "Cloned Workspace", "description": "Duplicate ws"},
        headers=alice_headers,
    )
    assert resp.status_code == 201
    cloned = resp.json()
    assert cloned["name"] == "Cloned Workspace"

    # Make Bob member first.
    client.post(
        f"/collaboration/workspaces/{ws_id}/members",
        json={"user_id": bob_id, "role": "editor"},
        headers=alice_headers,
    )

    # Transfer ownership to Bob.
    resp = client.post(
        f"/collaboration/workspaces/{ws_id}/transfer",
        json={"new_owner_id": bob_id},
        headers=alice_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["owner_id"] == bob_id
