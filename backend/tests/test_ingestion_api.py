"""Integration tests for the multimodal ingestion HTTP surface (inline runner + fake engine).

Exercises the full pipeline: upload → process (classification → OCR → image/table/figure extraction
→ multimodal chunking → metadata) → assets/ocr/chunks endpoints → retry/cancel → OCR caching.
"""

from __future__ import annotations


def _upload(client, headers, ws, name="paper.pdf"):
    r = client.post(f"/workspaces/{ws}/documents",
                    files=[("files", (name, b"%PDF-1.4 fake", "application/pdf"))], headers=headers)
    assert r.status_code in (200, 201), r.text
    return client.get(f"/workspaces/{ws}/documents", headers=headers).json()["items"][0]["id"]


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/documents/doc_x/process").status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.post(f"/workspaces/{ws}/documents/doc_x/process", headers=bob).status_code == 404


def test_process_missing_document_404(workspace):
    client, headers, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/documents/nope/process", headers=headers).status_code == 404


# ------------------------------------------------------------------ full pipeline
def test_process_completes_with_all_assets(workspace):
    client, headers, _, ws = workspace
    doc = _upload(client, headers, ws)

    r = client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers)
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "completed"                 # inline runner ran it
    assert job["doc_type"] == "mixed_pdf" and job["processing_type"] == "mixed"
    assert job["ocr_pages"] == 2
    assert job["image_count"] == 1 and job["table_count"] == 1 and job["figure_count"] == 1
    # 2 OCR text chunks + 1 image + 1 table + 1 figure = 5.
    assert job["chunk_count"] == 5
    assert job["ocr_confidence"] is not None

    # Document-level status mirror.
    st = client.get(f"/workspaces/{ws}/documents/{doc}/processing", headers=headers).json()
    assert st["status"] == "completed"


def test_extracted_assets_endpoint(workspace):
    client, headers, _, ws = workspace
    doc = _upload(client, headers, ws)
    client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers)

    assets = client.get(f"/workspaces/{ws}/documents/{doc}/assets", headers=headers).json()
    assert len(assets["images"]) == 1 and assets["images"][0]["image_type"] == "raster"
    assert len(assets["tables"]) == 1 and assets["tables"][0]["headers"] == ["Col A", "Col B"]
    assert len(assets["figures"]) == 1 and assets["figures"][0]["figure_type"] == "diagram"


def test_ocr_endpoint(workspace):
    client, headers, _, ws = workspace
    doc = _upload(client, headers, ws)
    client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers)

    ocr = client.get(f"/workspaces/{ws}/documents/{doc}/ocr", headers=headers).json()
    assert ocr["ocr_pages"] == 2 and ocr["language"] == "en"
    assert ocr["avg_confidence"] is not None
    assert all("recognized text" in p["text"] for p in ocr["pages"])


def test_multimodal_chunks_endpoint_and_filter(workspace):
    client, headers, _, ws = workspace
    doc = _upload(client, headers, ws)
    client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers)

    chunks = client.get(f"/workspaces/{ws}/documents/{doc}/multimodal-chunks", headers=headers).json()
    types = {c["chunk_type"] for c in chunks}
    assert {"ocr", "image", "table", "figure"} <= types
    assert all(c["embedding_status"] == "pending" for c in chunks)   # future embedding queue
    only_tables = client.get(f"/workspaces/{ws}/documents/{doc}/multimodal-chunks?chunk_type=table", headers=headers).json()
    assert len(only_tables) == 1 and only_tables[0]["chunk_type"] == "table"


def test_job_detail_has_logs(workspace):
    client, headers, _, ws = workspace
    doc = _upload(client, headers, ws)
    jid = client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers).json()["id"]
    detail = client.get(f"/workspaces/{ws}/processing/{jid}", headers=headers).json()
    assert detail["status"] == "completed"
    stages = {log["stage"] for log in detail["logs"]}
    assert "classification" in stages and "pipeline" in stages


# ------------------------------------------------------------------ caching + reprocess
def test_reprocess_skips_unchanged_and_caches_ocr(workspace):
    client, headers, _, ws = workspace
    doc = _upload(client, headers, ws)
    first = client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers).json()

    # Re-process WITHOUT force → same completed job (unchanged file, skip duplicate work).
    again = client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers).json()
    assert again["id"] == first["id"]

    # Force reprocess → new job, but OCR is served from cache (no duplicate OcrResult rows).
    forced = client.post(f"/workspaces/{ws}/documents/{doc}/process", json={"force": True}, headers=headers).json()
    assert forced["id"] != first["id"] and forced["status"] == "completed"
    ocr = client.get(f"/workspaces/{ws}/documents/{doc}/ocr", headers=headers).json()
    assert ocr["ocr_pages"] == 2  # still exactly 2 cached pages — OCR was not re-run


# ------------------------------------------------------------------ state transitions
def test_cancel_and_retry_state_errors(workspace):
    client, headers, _, ws = workspace
    doc = _upload(client, headers, ws)
    jid = client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers).json()["id"]
    # A completed job cannot be cancelled or retried.
    assert client.post(f"/workspaces/{ws}/processing/{jid}/cancel", headers=headers).status_code == 409
    assert client.post(f"/workspaces/{ws}/processing/{jid}/retry", headers=headers).status_code == 409
