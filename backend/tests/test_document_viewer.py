"""Integration tests for the Module-3 viewer endpoints (file, chunks, resolve, reading)."""

from __future__ import annotations


def _pdf(name):
    return (name, b"%PDF-1.4 fake bytes", "application/pdf")


def _upload(client, headers, ws, *files):
    return client.post(f"/workspaces/{ws}/documents", files=[("files", _pdf(n)) for n in files], headers=headers)


def _first(up):
    return up.json()["items"][0]["document"]


# ------------------------------------------------------------------ file serving
def test_get_file_streams_bytes(workspace):
    client, headers, _, ws = workspace
    doc = _first(_upload(client, headers, ws, "read.pdf"))
    r = client.get(f"/workspaces/{ws}/documents/{doc['id']}/file", headers=headers)
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 fake bytes"
    assert "application/pdf" in r.headers["content-type"]


def test_get_file_requires_auth_and_ownership(workspace, client):
    client, headers, _, ws = workspace
    doc_id = _first(_upload(client, headers, ws, "y.pdf"))["id"]
    # unauthenticated
    assert client.get(f"/workspaces/{ws}/documents/{doc_id}/file").status_code == 401
    # foreign user
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.get(f"/workspaces/{ws}/documents/{doc_id}/file", headers=bob).status_code == 404


# ------------------------------------------------------------------ chunks
def test_get_chunks_and_page_filter(workspace):
    client, headers, _, ws = workspace
    doc = _first(_upload(client, headers, ws, "c.pdf"))
    allc = client.get(f"/workspaces/{ws}/documents/{doc['id']}/chunks", headers=headers).json()
    assert allc["total"] == 3
    assert allc["vector_document_id"] == doc["vector_document_id"]
    assert all(c["page_number"] == 1 for c in allc["items"])
    assert allc["items"][0]["text"]

    p1 = client.get(f"/workspaces/{ws}/documents/{doc['id']}/chunks?page=1", headers=headers).json()
    assert p1["total"] == 3
    p2 = client.get(f"/workspaces/{ws}/documents/{doc['id']}/chunks?page=2", headers=headers).json()
    assert p2["total"] == 0


# ------------------------------------------------------------------ resolve citation
def test_resolve_by_vector_id(workspace):
    client, headers, _, ws = workspace
    doc = _first(_upload(client, headers, ws, "os.pdf"))
    r = client.get(f"/workspaces/{ws}/documents/by-vector/{doc['vector_document_id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == doc["id"]
    assert client.get(f"/workspaces/{ws}/documents/by-vector/doc_missing", headers=headers).status_code == 404


# ------------------------------------------------------------------ reading sessions
def test_reading_progress_upsert_and_restore(workspace):
    client, headers, _, ws = workspace
    doc = _first(_upload(client, headers, ws, "reading.pdf"))
    doc_id = doc["id"]

    # No session yet → null.
    assert client.get(f"/workspaces/{ws}/reading/{doc_id}/progress", headers=headers).json() is None

    r = client.put(
        f"/workspaces/{ws}/reading/{doc_id}/progress",
        json={"page": 5, "scroll_top": 320, "zoom": 125, "rotation": 90},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["page"] == 5 and r.json()["zoom"] == 125

    # Upsert (not duplicate): update the same session.
    client.put(f"/workspaces/{ws}/reading/{doc_id}/progress", json={"page": 8}, headers=headers)
    restored = client.get(f"/workspaces/{ws}/reading/{doc_id}/progress", headers=headers).json()
    assert restored["page"] == 8


def test_reading_history_recent_first(workspace):
    client, headers, _, ws = workspace
    d1 = _first(_upload(client, headers, ws, "one.pdf"))["id"]
    d2 = _first(_upload(client, headers, ws, "two.pdf"))["id"]
    client.put(f"/workspaces/{ws}/reading/{d1}/progress", json={"page": 2}, headers=headers)
    client.put(f"/workspaces/{ws}/reading/{d2}/progress", json={"page": 3}, headers=headers)

    hist = client.get(f"/workspaces/{ws}/reading/history", headers=headers).json()["items"]
    assert {h["document_id"] for h in hist} == {d1, d2}
    assert hist[0]["document_id"] == d2  # most recently updated first
    assert hist[0]["page"] == 3 and "display_name" in hist[0]


def test_reading_progress_foreign_document_404(workspace):
    client, headers, _, ws = workspace
    assert client.put(f"/workspaces/{ws}/reading/doc_nope/progress", json={"page": 1}, headers=headers).status_code == 404
