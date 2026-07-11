"""Integration tests for the Vision Intelligence HTTP surface (inline runner + fake engine).

Full flow: upload → Module-1 multimodal processing (extracts image/table/figure) → Module-2 vision
analysis (classify → caption → structure → embed) → caption write-back + chunk enrichment + the
analyses/captions/embedding/search endpoints.
"""

from __future__ import annotations


def _seed(client, headers, ws):
    """Upload a document and run Module-1 processing so visual assets exist to understand."""
    client.post(f"/workspaces/{ws}/documents",
                files=[("files", ("paper.pdf", b"%PDF-1.4 fake", "application/pdf"))], headers=headers)
    doc = client.get(f"/workspaces/{ws}/documents", headers=headers).json()["items"][0]["id"]
    client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers)  # extracts 1 image, 1 table, 1 figure
    return doc


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/documents/doc_x/vision").status_code == 401


def test_missing_document_404(workspace):
    client, headers, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/documents/nope/vision", headers=headers).status_code == 404


# ------------------------------------------------------------------ full pipeline
def test_vision_analyzes_all_assets(workspace):
    client, headers, _, ws = workspace
    doc = _seed(client, headers, ws)

    r = client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers)
    assert r.status_code == 202
    job = r.json()
    assert job["status"] == "completed"
    assert job["asset_count"] == 3 and job["analyzed_count"] == 3 and job["embedding_count"] == 3
    assert job["embedding_model"] == "fake-clip-vit"

    st = client.get(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers).json()
    assert st["status"] == "completed"


def test_analyses_classified_and_captioned(workspace):
    client, headers, _, ws = workspace
    doc = _seed(client, headers, ws)
    client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers)

    res = client.get(f"/workspaces/{ws}/documents/{doc}/vision/analyses", headers=headers).json()
    assert res["total"] == 3
    types = {a["image_type"] for a in res["items"]}
    assert "table" in types and "architecture_diagram" in types  # figure(diagram) + table classified
    # Every analysis has a semantic caption + an embedding.
    assert all(a["caption"] and a["has_embedding"] for a in res["items"])
    # The table analysis carries real structured understanding.
    table = next(a for a in res["items"] if a["image_type"] == "table")
    assert table["structured"]["kind"] == "table" and table["structured"]["columns"]


def test_captions_written_back_to_module1_assets(workspace):
    client, headers, _, ws = workspace
    doc = _seed(client, headers, ws)
    # Before vision: Module-1 table caption is "Table 1"; figure caption "System architecture".
    client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers)
    # After vision: the Module-1 asset captions are the richer vision captions.
    assets = client.get(f"/workspaces/{ws}/documents/{doc}/assets", headers=headers).json()
    assert "columns" in assets["tables"][0]["caption"].lower() or "table" in assets["tables"][0]["caption"].lower()
    assert "p." in assets["figures"][0]["caption"]


def test_multimodal_chunks_enriched(workspace):
    client, headers, _, ws = workspace
    doc = _seed(client, headers, ws)
    client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers)
    chunks = client.get(f"/workspaces/{ws}/documents/{doc}/multimodal-chunks?chunk_type=figure", headers=headers).json()
    assert chunks and chunks[0]["meta"].get("vision_analyzed") is True
    assert chunks[0]["meta"].get("vision_image_type") == "architecture_diagram"
    assert chunks[0]["embedding_status"] == "pending"  # still not embedded into FAISS


def test_captions_endpoint(workspace):
    client, headers, _, ws = workspace
    doc = _seed(client, headers, ws)
    client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers)
    caps = client.get(f"/workspaces/{ws}/documents/{doc}/vision/captions", headers=headers).json()
    assert len(caps) == 3 and all(c["caption"] for c in caps)


def test_single_analysis_embedding_and_search(workspace):
    client, headers, _, ws = workspace
    doc = _seed(client, headers, ws)
    client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers)
    items = client.get(f"/workspaces/{ws}/documents/{doc}/vision/analyses", headers=headers).json()["items"]
    aid = items[0]["id"]

    detail = client.get(f"/workspaces/{ws}/vision/analyses/{aid}", headers=headers)
    assert detail.status_code == 200 and detail.json()["id"] == aid

    emb = client.get(f"/workspaces/{ws}/vision/analyses/{aid}/embedding?include_vector=true", headers=headers).json()
    assert emb["dim"] == 16 and emb["model_family"] == "fake" and len(emb["vector"]) == 16
    # Without the flag the vector is omitted (it can be large).
    emb2 = client.get(f"/workspaces/{ws}/vision/analyses/{aid}/embedding", headers=headers).json()
    assert emb2["vector"] is None

    # Visual-knowledge search index.
    search = client.get(f"/workspaces/{ws}/vision/search-meta?image_type=table", headers=headers).json()
    assert search["total"] == 1 and search["items"][0]["image_type"] == "table"


# ------------------------------------------------------------------ empty doc + reprocess + state
def test_document_with_no_assets_completes_zero(workspace):
    client, headers, _, ws = workspace
    client.post(f"/workspaces/{ws}/documents",
                files=[("files", ("empty.pdf", b"%PDF-1.4", "application/pdf"))], headers=headers)
    doc = client.get(f"/workspaces/{ws}/documents", headers=headers).json()["items"][0]["id"]
    # No Module-1 processing → no extracted assets.
    job = client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers).json()
    assert job["status"] == "completed" and job["asset_count"] == 0 and job["analyzed_count"] == 0


def test_reprocess_and_state_errors(workspace):
    client, headers, _, ws = workspace
    doc = _seed(client, headers, ws)
    first = client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers).json()
    again = client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers).json()
    assert again["id"] == first["id"]                       # completed job reused
    forced = client.post(f"/workspaces/{ws}/documents/{doc}/vision", json={"force": True}, headers=headers).json()
    assert forced["id"] != first["id"] and forced["analyzed_count"] == 3
    # A completed job cannot be cancelled or retried.
    assert client.post(f"/workspaces/{ws}/vision/job/{forced['id']}/cancel", headers=headers).status_code == 409
    assert client.post(f"/workspaces/{ws}/vision/job/{forced['id']}/retry", headers=headers).status_code == 409


def test_job_detail_has_logs(workspace):
    client, headers, _, ws = workspace
    doc = _seed(client, headers, ws)
    jid = client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers).json()["id"]
    detail = client.get(f"/workspaces/{ws}/vision/job/{jid}", headers=headers).json()
    assert detail["status"] == "completed" and len(detail["logs"]) >= 1
