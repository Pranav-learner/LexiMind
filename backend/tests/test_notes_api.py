"""Integration tests for the notes HTTP surface (inline runner + fake engine).

Exercises every creation path, autosave/conflict, AI generation, AI-assist, tags, conversions
(summary → note, chat message → note), export, and workspace-counter integration.
"""

from __future__ import annotations


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/notes").status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.post(f"/workspaces/{ws}/notes", json={"title": "x"}, headers=bob).status_code == 404


# ------------------------------------------------------------------ manual create (blank/selection)
def test_create_blank_note(workspace):
    client, headers, _, ws = workspace
    r = client.post(f"/workspaces/{ws}/notes", json={"title": "My Note", "content": "hello world here"}, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "My Note" and body["status"] == "ready"
    assert body["word_count"] == 3 and body["created_by"] == "user"
    assert body["content"] == "hello world here"
    # Workspace note_count bumped.
    assert client.get(f"/workspaces/{ws}", headers=headers).json()["note_count"] == 1


def test_create_note_from_selection_with_citations(workspace):
    client, headers, _, ws = workspace
    r = client.post(f"/workspaces/{ws}/notes", json={
        "source": "selection", "content": "selected passage",
        "citations": [{"document_id": "doc_x", "page_number": 5, "citation_text": "evidence"}],
    }, headers=headers)
    assert r.status_code == 201
    assert r.json()["citation_count"] == 1
    assert r.json()["citations"][0]["page_number"] == 5


# ------------------------------------------------------------------ AI generation (async, inline)
def test_generate_completes_with_sections_and_citations(workspace):
    client, headers, _, ws = workspace
    r = client.post(f"/workspaces/{ws}/notes/generate", json={"note_type": "study"}, headers=headers)
    assert r.status_code == 202
    nid = r.json()["id"]
    assert r.json()["created_by"] == "ai"

    st = client.get(f"/workspaces/{ws}/notes/{nid}/status", headers=headers).json()
    assert st["status"] == "completed" and st["progress"] == 100 and st["section_count"] == 2

    detail = client.get(f"/workspaces/{ws}/notes/{nid}", headers=headers).json()
    assert [s["heading"] for s in detail["sections"]] == ["Overview", "Key Concepts"]
    assert "## Overview" in detail["content"]
    assert detail["citations"][0]["page_number"] == 3
    # Live outline is derived from the assembled markdown headings.
    assert [o["text"] for o in detail["outline"]] == ["Overview", "Key Concepts"]


def test_generate_validation_error(workspace):
    client, headers, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/notes/generate", json={"note_type": "essay"}, headers=headers).status_code == 422
    assert client.post(f"/workspaces/{ws}/notes/generate", json={"note_type": "study", "scope": "document"}, headers=headers).status_code == 422


# ------------------------------------------------------------------ autosave + optimistic concurrency
def test_autosave_and_conflict(workspace):
    client, headers, _, ws = workspace
    nid = client.post(f"/workspaces/{ws}/notes", json={"content": "v1"}, headers=headers).json()["id"]

    r = client.put(f"/workspaces/{ws}/notes/{nid}/content", json={"content": "v2 longer body", "base_version": 1}, headers=headers)
    assert r.status_code == 200 and r.json()["version"] == 2

    # Stale base_version → 409 conflict (never clobber a newer edit).
    conflict = client.put(f"/workspaces/{ws}/notes/{nid}/content", json={"content": "v3", "base_version": 1}, headers=headers)
    assert conflict.status_code == 409


# ------------------------------------------------------------------ AI-assisted editing
def test_assist_operations(workspace):
    client, headers, _, ws = workspace
    nid = client.post(f"/workspaces/{ws}/notes", json={"content": "body"}, headers=headers).json()["id"]
    r = client.post(f"/workspaces/{ws}/notes/{nid}/assist",
                    json={"operation": "simplify", "selection": "complex text"}, headers=headers)
    assert r.status_code == 200 and r.json()["result"] == "[simplify] complex text"
    # Unknown op rejected.
    assert client.post(f"/workspaces/{ws}/notes/{nid}/assist",
                       json={"operation": "translate", "selection": "x"}, headers=headers).status_code == 422


# ------------------------------------------------------------------ metadata: pin/favorite/archive + filters
def test_pin_archive_and_list_filters(workspace):
    client, headers, _, ws = workspace
    a = client.post(f"/workspaces/{ws}/notes", json={"title": "A", "content": "x"}, headers=headers).json()["id"]
    client.post(f"/workspaces/{ws}/notes", json={"title": "B", "content": "y"}, headers=headers)
    client.patch(f"/workspaces/{ws}/notes/{a}", json={"is_pinned": True}, headers=headers)

    listed = client.get(f"/workspaces/{ws}/notes", headers=headers).json()
    assert listed["total"] == 2 and listed["items"][0]["title"] == "A"  # pinned first
    assert client.get(f"/workspaces/{ws}/notes?pinned=pinned", headers=headers).json()["total"] == 1

    client.patch(f"/workspaces/{ws}/notes/{a}", json={"is_archived": True}, headers=headers)
    assert client.get(f"/workspaces/{ws}/notes", headers=headers).json()["total"] == 1  # archived hidden
    assert client.get(f"/workspaces/{ws}/notes?archived=archived", headers=headers).json()["total"] == 1


def test_search_matches_content(workspace):
    client, headers, _, ws = workspace
    client.post(f"/workspaces/{ws}/notes", json={"title": "A", "content": "neural networks"}, headers=headers)
    client.post(f"/workspaces/{ws}/notes", json={"title": "B", "content": "databases"}, headers=headers)
    assert client.get(f"/workspaces/{ws}/notes?search=neural", headers=headers).json()["total"] == 1


# ------------------------------------------------------------------ tags
def test_tag_crud_and_attach_and_filter(workspace):
    client, headers, _, ws = workspace
    t = client.post(f"/workspaces/{ws}/tags", json={"name": "ML", "color": "#123456"}, headers=headers)
    assert t.status_code == 201
    tid = t.json()["id"]
    # Duplicate (case-insensitive) → 409.
    assert client.post(f"/workspaces/{ws}/tags", json={"name": "ml"}, headers=headers).status_code == 409

    nid = client.post(f"/workspaces/{ws}/notes", json={"content": "x"}, headers=headers).json()["id"]
    r = client.put(f"/workspaces/{ws}/notes/{nid}/tags", json={"tag_ids": [tid]}, headers=headers)
    assert [tg["name"] for tg in r.json()["tags"]] == ["ML"]

    # Filter notes by tag.
    assert client.get(f"/workspaces/{ws}/notes?tag_id={tid}", headers=headers).json()["total"] == 1
    # Tag usage counter.
    assert client.get(f"/workspaces/{ws}/tags", headers=headers).json()["items"][0]["note_count"] == 1

    # Rename + delete.
    assert client.patch(f"/workspaces/{ws}/tags/{tid}", json={"name": "MachineLearning"}, headers=headers).json()["name"] == "MachineLearning"
    assert client.delete(f"/workspaces/{ws}/tags/{tid}", headers=headers).status_code == 204
    assert client.get(f"/workspaces/{ws}/notes/{nid}", headers=headers).json()["tags"] == []


# ------------------------------------------------------------------ duplicate / export / delete
def test_duplicate_export_delete(workspace):
    client, headers, _, ws = workspace
    nid = client.post(f"/workspaces/{ws}/notes", json={"title": "Doc", "content": "## Heading\n\nbody"}, headers=headers).json()["id"]

    dup = client.post(f"/workspaces/{ws}/notes/{nid}/duplicate", headers=headers)
    assert dup.status_code == 201 and dup.json()["title"].endswith("(copy)")

    exp = client.get(f"/workspaces/{ws}/notes/{nid}/export", headers=headers)
    assert exp.status_code == 200 and "text/markdown" in exp.headers["content-type"]
    assert "# Doc" in exp.text and "## Heading" in exp.text

    assert client.delete(f"/workspaces/{ws}/notes/{nid}", headers=headers).status_code == 204
    assert client.get(f"/workspaces/{ws}/notes/{nid}/status", headers=headers).status_code == 404


# ------------------------------------------------------------------ conversions (summary → note, chat → note)
def test_convert_from_summary(workspace):
    client, headers, _, ws = workspace
    sid = client.post(f"/workspaces/{ws}/summaries", json={"summary_type": "standard"}, headers=headers).json()["id"]
    r = client.post(f"/workspaces/{ws}/notes/from-summary/{sid}", headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert body["source"] == "summary" and body["section_count"] == 2
    assert "## Overview" in body["content"] and body["citation_count"] == 2


def test_convert_from_chat_message(workspace):
    client, headers, _, ws = workspace
    conv = client.post(f"/workspaces/{ws}/conversations", json={"title": "Chat"}, headers=headers).json()
    cid = conv["id"]
    # Send a message (fake chat engine → assistant reply + a citation).
    msg = client.post(f"/workspaces/{ws}/conversations/{cid}/messages",
                      json={"content": "What is virtual memory?"}, headers=headers)
    assert msg.status_code in (200, 201), msg.text
    assistant = msg.json()["assistant"]
    r = client.post(f"/workspaces/{ws}/notes/from-message/{assistant['id']}", headers=headers)
    assert r.status_code == 201
    assert r.json()["source"] == "chat" and r.json()["citation_count"] == 1


# ------------------------------------------------------------------ document-scoped generate + regenerate/cancel
def test_generate_document_scope_and_regenerate(workspace):
    client, headers, _, ws = workspace
    r = client.post(f"/workspaces/{ws}/notes/generate",
                    json={"note_type": "detailed", "scope": "document", "document_id": "doc_abc"}, headers=headers)
    assert r.status_code == 202
    nid = r.json()["id"]
    assert client.get(f"/workspaces/{ws}/notes/{nid}/status", headers=headers).json()["status"] == "completed"

    regen = client.post(f"/workspaces/{ws}/notes/{nid}/regenerate", headers=headers)
    assert regen.status_code == 200 and regen.json()["version"] >= 2

    # Cancelling a completed note is a 409.
    assert client.post(f"/workspaces/{ws}/notes/{nid}/cancel", headers=headers).status_code == 409
