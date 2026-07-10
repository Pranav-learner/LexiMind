"""Integration tests for the summaries HTTP surface (inline runner + fake engine)."""

from __future__ import annotations


def _gen(client, headers, ws, **body):
    return client.post(f"/workspaces/{ws}/summaries", json=body, headers=headers)


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/summaries").status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert _gen(client, bob, ws, summary_type="quick").status_code == 404


# ------------------------------------------------------------------ generate + status + detail
def test_generate_completes_with_sections_and_citations(workspace):
    client, headers, _, ws = workspace
    r = _gen(client, headers, ws, summary_type="standard")
    assert r.status_code == 202
    sid = r.json()["id"]

    # Inline runner already ran → completed.
    st = client.get(f"/workspaces/{ws}/summaries/{sid}/status", headers=headers).json()
    assert st["status"] == "completed"
    assert st["progress"] == 100
    assert st["section_count"] == 2

    detail = client.get(f"/workspaces/{ws}/summaries/{sid}", headers=headers).json()
    assert [s["heading"] for s in detail["sections"]] == ["Overview", "Conclusions"]
    assert detail["sections"][0]["citations"][0]["page_number"] == 3

    # Workspace summary_count bumped.
    assert client.get(f"/workspaces/{ws}", headers=headers).json()["summary_count"] == 1


def test_generate_validation_errors(workspace):
    client, headers, _, ws = workspace
    assert _gen(client, headers, ws, summary_type="essay").status_code == 422
    assert _gen(client, headers, ws, summary_type="quick", scope="document").status_code == 422


def test_document_and_multi_scope(workspace):
    client, headers, _, ws = workspace
    assert _gen(client, headers, ws, summary_type="detailed", scope="document", document_id="doc_1").status_code == 202
    assert _gen(client, headers, ws, summary_type="standard", scope="multi", document_ids=["d1", "d2"]).status_code == 202


# ------------------------------------------------------------------ list / filter
def test_list_and_filter(workspace):
    client, headers, _, ws = workspace
    _gen(client, headers, ws, summary_type="quick")
    _gen(client, headers, ws, summary_type="detailed")
    assert client.get(f"/workspaces/{ws}/summaries", headers=headers).json()["total"] == 2
    assert client.get(f"/workspaces/{ws}/summaries?summary_type=quick", headers=headers).json()["total"] == 1
    assert client.get(f"/workspaces/{ws}/summaries?status=completed", headers=headers).json()["total"] == 2


# ------------------------------------------------------------------ rename / regenerate / duplicate / export / delete
def test_rename_regenerate_duplicate_export_delete(workspace):
    client, headers, _, ws = workspace
    sid = _gen(client, headers, ws, summary_type="standard").json()["id"]

    assert client.patch(f"/workspaces/{ws}/summaries/{sid}", json={"title": "My Summary"}, headers=headers).json()["title"] == "My Summary"

    regen = client.post(f"/workspaces/{ws}/summaries/{sid}/regenerate", headers=headers)
    assert regen.status_code == 200
    assert regen.json()["version"] == 2
    assert client.get(f"/workspaces/{ws}/summaries/{sid}/status", headers=headers).json()["status"] == "completed"

    dup = client.post(f"/workspaces/{ws}/summaries/{sid}/duplicate", headers=headers)
    assert dup.status_code == 201
    assert dup.json()["title"].endswith("(copy)")
    assert len(dup.json()["sections"]) == 2

    exp = client.get(f"/workspaces/{ws}/summaries/{sid}/export", headers=headers)
    assert exp.status_code == 200
    assert "text/markdown" in exp.headers["content-type"]
    assert "# My Summary" in exp.text and "## Overview" in exp.text and "**Sources:**" in exp.text

    assert client.delete(f"/workspaces/{ws}/summaries/{sid}", headers=headers).status_code == 204
    assert client.get(f"/workspaces/{ws}/summaries/{sid}/status", headers=headers).status_code == 404


def test_cancel_completed_conflicts(workspace):
    client, headers, _, ws = workspace
    sid = _gen(client, headers, ws, summary_type="quick").json()["id"]
    # Inline runner completed it → cancel is a 409 state error.
    assert client.post(f"/workspaces/{ws}/summaries/{sid}/cancel", headers=headers).status_code == 409
