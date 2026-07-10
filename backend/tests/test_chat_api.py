"""Integration tests for the chat HTTP surface (CRUD, send, streaming, search, isolation)."""

from __future__ import annotations

import json


def _mk(client, headers, ws, **body):
    return client.post(f"/workspaces/{ws}/conversations", json=body, headers=headers)


def _conv_id(client, headers, ws, **body):
    return _mk(client, headers, ws, **body).json()["id"]


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/conversations").status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.post(f"/workspaces/{ws}/conversations", json={}, headers=bob).status_code == 404


# ------------------------------------------------------------------ conversation lifecycle
def test_conversation_lifecycle(workspace):
    client, headers, _, ws = workspace
    cid = _conv_id(client, headers, ws, title="My Chat")

    assert client.get(f"/workspaces/{ws}/conversations/{cid}", headers=headers).json()["title"] == "My Chat"
    assert client.get(f"/workspaces/{ws}/conversations", headers=headers).json()["total"] == 1

    # rename
    assert client.patch(f"/workspaces/{ws}/conversations/{cid}", json={"title": "Renamed"}, headers=headers).json()["title"] == "Renamed"
    # pin floats to top + pinned filter
    assert client.post(f"/workspaces/{ws}/conversations/{cid}/pin", headers=headers).json()["is_pinned"] is True
    assert client.get(f"/workspaces/{ws}/conversations?pinned=pinned", headers=headers).json()["total"] == 1
    client.post(f"/workspaces/{ws}/conversations/{cid}/unpin", headers=headers)
    # archive/restore
    assert client.post(f"/workspaces/{ws}/conversations/{cid}/archive", headers=headers).json()["is_archived"] is True
    assert client.get(f"/workspaces/{ws}/conversations", headers=headers).json()["total"] == 0
    assert client.get(f"/workspaces/{ws}/conversations?archived=archived", headers=headers).json()["total"] == 1
    client.post(f"/workspaces/{ws}/conversations/{cid}/restore", headers=headers)
    # delete
    assert client.delete(f"/workspaces/{ws}/conversations/{cid}", headers=headers).status_code == 204
    assert client.get(f"/workspaces/{ws}/conversations/{cid}", headers=headers).status_code == 404


def test_create_bumps_workspace_chat_count(workspace):
    client, headers, _, ws = workspace
    _conv_id(client, headers, ws)
    assert client.get(f"/workspaces/{ws}", headers=headers).json()["chat_count"] == 1


# ------------------------------------------------------------------ send message (non-streaming)
def test_send_message_persists_and_cites(workspace):
    client, headers, _, ws = workspace
    cid = _conv_id(client, headers, ws)  # default title
    r = client.post(f"/workspaces/{ws}/conversations/{cid}/messages", json={"content": "What is paging?"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["user"]["role"] == "user"
    assert body["assistant"]["role"] == "assistant"
    assert body["assistant"]["content"] == "Hello world"
    assert body["assistant"]["citation_count"] == 1
    assert body["assistant"]["citations"][0]["page_number"] == 42

    # Auto-title from first message + history endpoint.
    assert client.get(f"/workspaces/{ws}/conversations/{cid}", headers=headers).json()["title"] == "What is paging?"
    msgs = client.get(f"/workspaces/{ws}/conversations/{cid}/messages", headers=headers).json()
    assert msgs["total"] == 2
    assert msgs["items"][0]["role"] == "user"


# ------------------------------------------------------------------ streaming SSE
def test_stream_message_sse(workspace):
    client, headers, _, ws = workspace
    cid = _conv_id(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/conversations/{cid}/messages/stream", json={"content": "stream this"}, headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = []
    for block in r.text.strip().split("\n\n"):
        if not block.strip():
            continue
        etype = next((l.split(": ", 1)[1] for l in block.splitlines() if l.startswith("event: ")), None)
        data = next((l.split(": ", 1)[1] for l in block.splitlines() if l.startswith("data: ")), None)
        events.append((etype, json.loads(data) if data else None))

    types = [e[0] for e in events]
    assert types[0] == "user"
    assert "token" in types
    assert types[-1] == "done"
    tokens = "".join(e[1]["text"] for e in events if e[0] == "token")
    assert tokens == "Hello world"
    done = [e[1] for e in events if e[0] == "done"][0]
    assert done["content"] == "Hello world"
    assert done["citations"][0]["page_number"] == 42

    # Persisted after streaming.
    assert client.get(f"/workspaces/{ws}/conversations/{cid}/messages", headers=headers).json()["total"] == 2


# ------------------------------------------------------------------ duplicate + search
def test_duplicate_and_search(workspace):
    client, headers, _, ws = workspace
    cid = _conv_id(client, headers, ws, title="Original")
    client.post(f"/workspaces/{ws}/conversations/{cid}/messages", json={"content": "mitochondria facts"}, headers=headers)

    dup = client.post(f"/workspaces/{ws}/conversations/{cid}/duplicate", headers=headers)
    assert dup.status_code == 201
    assert dup.json()["title"] == "Original (copy)"

    # Broad search finds by message content.
    found = client.get(f"/workspaces/{ws}/conversations/search?q=mitochondria", headers=headers).json()
    assert len(found) >= 1


def test_workspace_isolation(workspace, client):
    client, headers, user_id, ws1 = workspace
    # same user, second workspace
    ws2 = client.post("/workspaces", json={"name": "Second"}, headers=headers).json()["id"]
    _conv_id(client, headers, ws1, title="in ws1")
    assert client.get(f"/workspaces/{ws1}/conversations", headers=headers).json()["total"] == 1
    assert client.get(f"/workspaces/{ws2}/conversations", headers=headers).json()["total"] == 0
