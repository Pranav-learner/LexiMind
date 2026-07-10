"""Integration tests: the full document lifecycle over the real HTTP surface.

Uses the minimal app (auth + workspace + document routers) with the vector store / ingestion
overridden by in-memory fakes (see conftest). Exercises:
upload → processing → indexing → search → details → rename → archive/restore → reindex → delete.
"""

from __future__ import annotations


def _pdf(name):
    return (name, b"%PDF-1.4 fake bytes", "application/pdf")


def _upload(client, headers, ws, *files):
    payload = [("files", _pdf(n)) for n in files]
    return client.post(f"/workspaces/{ws}/documents", files=payload, headers=headers)


# ------------------------------------------------------------------ auth / scoping
def test_upload_requires_auth(workspace):
    client, _, _, ws = workspace
    r = client.post(f"/workspaces/{ws}/documents", files=[("files", _pdf("a.pdf"))])
    assert r.status_code == 401


def test_upload_to_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    # A different user must not upload into someone else's workspace.
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    r = _upload(client, bob, ws, "a.pdf")
    assert r.status_code == 404


# ------------------------------------------------------------------ upload + processing
def test_single_upload_processes_and_indexes(workspace, fake_index):
    client, headers, _, ws = workspace
    vs, bm25 = fake_index
    r = _upload(client, headers, ws, "report.pdf")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["uploaded"] == 1 and body["failed"] == 0
    doc = body["items"][0]["document"]
    assert doc["processing_status"] == "ready"
    assert doc["indexing_status"] == "indexed"
    assert doc["upload_progress"] == 100
    assert doc["chunk_count"] == 3
    assert doc["page_count"] == 2
    assert doc["embedding_model"] == "all-MiniLM-L6-v2"
    assert doc["embedding_dimension"] == 384
    assert doc["language"] == "en"
    assert len(vs.metadata) == 3            # chunks landed in the (fake) vector store
    assert bm25.added == 3

    # Workspace counter bumped.
    ws_row = client.get(f"/workspaces/{ws}", headers=headers).json()
    assert ws_row["document_count"] == 1


def test_multi_upload(workspace, fake_index):
    client, headers, _, ws = workspace
    r = _upload(client, headers, ws, "a.pdf", "b.pdf", "c.pdf")
    assert r.status_code == 201
    assert r.json()["uploaded"] == 3
    assert len(fake_index[0].metadata) == 9


def test_unsupported_type_and_duplicate_are_per_item_failures(workspace):
    client, headers, _, ws = workspace
    # Unsupported extension → failed item, batch still 201.
    r = client.post(f"/workspaces/{ws}/documents", files=[("files", ("evil.exe", b"x", "application/octet-stream"))], headers=headers)
    assert r.status_code == 201
    assert r.json()["failed"] == 1
    assert r.json()["uploaded"] == 0

    _upload(client, headers, ws, "same.pdf")
    dup = _upload(client, headers, ws, "same.pdf")
    assert dup.json()["failed"] == 1
    assert "already exists" in dup.json()["items"][0]["error"]


# ------------------------------------------------------------------ list / search / filter / sort
def test_list_search_sort_paginate(workspace):
    client, headers, _, ws = workspace
    _upload(client, headers, ws, "alpha.pdf", "beta.pdf", "gamma.pdf")

    lst = client.get(f"/workspaces/{ws}/documents", headers=headers).json()
    assert lst["total"] == 3 and lst["page"] == 1

    found = client.get(f"/workspaces/{ws}/documents?search=alpha", headers=headers).json()
    assert found["total"] == 1

    page = client.get(f"/workspaces/{ws}/documents?page=1&page_size=2", headers=headers).json()
    assert len(page["items"]) == 2 and page["pages"] == 2

    asc = client.get(f"/workspaces/{ws}/documents?sort_by=display_name&order=asc", headers=headers).json()
    names = [i["display_name"] for i in asc["items"]]
    assert names == sorted(names)


# ------------------------------------------------------------------ details / index health
def test_details_include_index_health(workspace):
    client, headers, _, ws = workspace
    up = _upload(client, headers, ws, "d.pdf").json()
    doc_id = up["items"][0]["document"]["id"]
    detail = client.get(f"/workspaces/{ws}/documents/{doc_id}", headers=headers).json()
    assert detail["index_health"]["chunk_count"] == 3
    assert detail["index_health"]["faiss_status"] == "indexed"
    assert detail["index_health"]["bm25_status"] == "indexed"
    assert detail["index_health"]["index_health"] == "healthy"


# ------------------------------------------------------------------ rename
def test_rename(workspace):
    client, headers, _, ws = workspace
    up = _upload(client, headers, ws, "orig.pdf").json()
    doc_id = up["items"][0]["document"]["id"]
    r = client.patch(f"/workspaces/{ws}/documents/{doc_id}", json={"display_name": "My Report"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["display_name"] == "My Report"
    assert r.json()["filename"] == "orig.pdf"


# ------------------------------------------------------------------ archive / restore
def test_archive_hides_from_active_and_marks_excluded(workspace, db_session):
    client, headers, _, ws = workspace
    up = _upload(client, headers, ws, "arch.pdf").json()
    doc = up["items"][0]["document"]
    doc_id = doc["id"]

    client.post(f"/workspaces/{ws}/documents/{doc_id}/archive", headers=headers)
    active = client.get(f"/workspaces/{ws}/documents", headers=headers).json()
    assert active["total"] == 0
    archived = client.get(f"/workspaces/{ws}/documents?archived=archived", headers=headers).json()
    assert archived["total"] == 1

    # Archived doc is on the retrieval exclusion list (keeps it out of /query).
    from app.documents.repository import DocumentRepository
    excluded = DocumentRepository(db_session).list_excluded_vector_ids(ws)
    assert doc["vector_document_id"] in excluded

    client.post(f"/workspaces/{ws}/documents/{doc_id}/restore", headers=headers)
    assert client.get(f"/workspaces/{ws}/documents", headers=headers).json()["total"] == 1


# ------------------------------------------------------------------ reindex
def test_reindex_replaces_chunks(workspace, fake_index):
    client, headers, _, ws = workspace
    up = _upload(client, headers, ws, "r.pdf").json()
    doc_id = up["items"][0]["document"]["id"]
    assert len(fake_index[0].metadata) == 3

    r = client.post(f"/workspaces/{ws}/documents/{doc_id}/reindex", headers=headers)
    assert r.status_code == 200
    assert r.json()["indexing_status"] == "indexed"
    # replace_existing → still 3, not 6 (idempotent).
    assert len(fake_index[0].metadata) == 3


# ------------------------------------------------------------------ delete (soft + permanent)
def test_soft_delete_then_permanent_purges_chunks(workspace, fake_index):
    client, headers, _, ws = workspace
    a = _upload(client, headers, ws, "keep.pdf").json()["items"][0]["document"]["id"]
    b = _upload(client, headers, ws, "drop.pdf").json()["items"][0]["document"]["id"]
    vs = fake_index[0]
    assert len(vs.metadata) == 6

    # Soft delete: gone from list, chunks remain (reversible).
    assert client.delete(f"/workspaces/{ws}/documents/{a}", headers=headers).status_code == 204
    assert client.get(f"/workspaces/{ws}/documents", headers=headers).json()["total"] == 1
    assert len(vs.metadata) == 6

    # Permanent delete: chunks purged from the vector store.
    assert client.delete(f"/workspaces/{ws}/documents/{b}?permanent=true", headers=headers).status_code == 204
    assert len(vs.metadata) == 3   # only 'keep.pdf' chunks remain

    # Workspace counter reflects both deletions.
    ws_row = client.get(f"/workspaces/{ws}", headers=headers).json()
    assert ws_row["document_count"] == 0


def test_full_lifecycle(workspace, fake_index):
    """create → get → list → rename → archive → restore → reindex → delete, asserting each step."""
    client, headers, _, ws = workspace
    doc = _upload(client, headers, ws, "life.pdf").json()["items"][0]["document"]
    doc_id = doc["id"]

    assert client.get(f"/workspaces/{ws}/documents/{doc_id}", headers=headers).status_code == 200
    assert client.get(f"/workspaces/{ws}/documents", headers=headers).json()["total"] == 1
    assert client.patch(f"/workspaces/{ws}/documents/{doc_id}", json={"description": "d"}, headers=headers).json()["description"] == "d"
    assert client.post(f"/workspaces/{ws}/documents/{doc_id}/archive", headers=headers).json()["is_archived"] is True
    assert client.post(f"/workspaces/{ws}/documents/{doc_id}/restore", headers=headers).json()["is_archived"] is False
    assert client.post(f"/workspaces/{ws}/documents/{doc_id}/reindex", headers=headers).status_code == 200
    assert client.delete(f"/workspaces/{ws}/documents/{doc_id}?permanent=true", headers=headers).status_code == 204
    assert client.get(f"/workspaces/{ws}/documents/{doc_id}", headers=headers).status_code == 404
