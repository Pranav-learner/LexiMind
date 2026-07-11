"""Integration tests for the Multimodal Workspace orchestrator (the Phase-4 capstone).

The one-call unified flow: POST /ai/ingest → create + text-index + auto multimodal processing + auto
vision → assets/timeline/pipeline-status/overview → AI actions routing to the existing generation
services. Everything runs inline in tests (fake index/ingestor + inline processing/vision/generation
runners) — proving the whole platform integrates end to end without the user choosing any pipeline.
"""

from __future__ import annotations


def _ingest(client, headers, ws, name="paper.pdf"):
    return client.post(f"/workspaces/{ws}/ai/ingest",
                       files=[("files", (name, b"%PDF-1.4 fake", "application/pdf"))], headers=headers)


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/ai/assets").status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.get(f"/workspaces/{ws}/ai/assets", headers=bob).status_code == 404


# ------------------------------------------------------------------ unified ingest (auto pipelines)
def test_unified_ingest_runs_all_pipelines(workspace):
    client, headers, _, ws = workspace
    r = _ingest(client, headers, ws)
    assert r.status_code == 201
    body = r.json()
    assert body["uploaded"] == 1
    item = body["items"][0]
    assert item["success"] and item["document_id"] and item["processing_job_id"] and item["vision_job_id"]
    assert item["media_kind"] == "pdf"

    doc = item["document_id"]
    # Multimodal processing ran automatically → assets extracted.
    proc = client.get(f"/workspaces/{ws}/documents/{doc}/processing", headers=headers).json()
    assert proc["status"] == "completed" and proc["image_count"] == 1
    # Vision ran automatically (after processing) → assets understood + captions written back.
    vis = client.get(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers).json()
    assert vis["status"] == "completed" and vis["analyzed_count"] == 3


# ------------------------------------------------------------------ pipeline status (unified)
def test_pipeline_status_unifies_all_stages(workspace):
    client, headers, _, ws = workspace
    doc = _ingest(client, headers, ws).json()["items"][0]["document_id"]
    st = client.get(f"/workspaces/{ws}/ai/pipeline-status/{doc}", headers=headers).json()
    assert st["text_indexed"] is True
    assert st["processing"]["status"] == "completed" and st["vision"]["status"] == "completed"
    assert st["counts"]["images"] == 1 and st["counts"]["tables"] == 1 and st["counts"]["vision_assets"] == 3
    assert st["ready"] is True


def test_pipeline_status_missing_document_404(workspace):
    client, headers, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/ai/pipeline-status/nope", headers=headers).status_code == 404


# ------------------------------------------------------------------ asset explorer
def test_asset_explorer_aggregates_modalities(workspace):
    client, headers, _, ws = workspace
    _ingest(client, headers, ws)
    res = client.get(f"/workspaces/{ws}/ai/assets", headers=headers).json()
    counts = res["counts"]
    assert counts.get("document") == 1
    # Vision produced a diagram, a table, and an image asset.
    assert counts.get("diagram", 0) >= 1 and counts.get("table", 0) >= 1 and counts.get("image", 0) >= 1
    types = {a["asset_type"] for a in res["items"]}
    assert {"document", "diagram", "table"} <= types
    # Filter by a single asset type.
    diagrams = client.get(f"/workspaces/{ws}/ai/assets?asset_type=diagram", headers=headers).json()
    assert all(a["asset_type"] == "diagram" for a in diagrams["items"])


# ------------------------------------------------------------------ timeline
def test_timeline_shows_pipeline_events(workspace):
    client, headers, _, ws = workspace
    _ingest(client, headers, ws)
    tl = client.get(f"/workspaces/{ws}/ai/timeline", headers=headers).json()["items"]
    types = {e["type"] for e in tl}
    assert {"upload", "processing", "vision"} <= types
    assert all(e["route"] for e in tl)


# ------------------------------------------------------------------ AI workspace actions
def test_ai_action_routes_to_generation_services(workspace):
    client, headers, _, ws = workspace
    doc = _ingest(client, headers, ws).json()["items"][0]["document_id"]

    # Notes from diagrams → routes to the note generation service (inline → completed).
    notes = client.post(f"/workspaces/{ws}/ai/action", json={"action": "notes", "document_id": doc, "focus": "diagrams"}, headers=headers).json()
    assert notes["asset_type"] == "note" and notes["status"] == "completed" and "/notes/" in notes["route"]

    # Flashcards from tables → deck generation.
    cards = client.post(f"/workspaces/{ws}/ai/action", json={"action": "flashcards", "document_id": doc, "focus": "tables", "count": 4}, headers=headers).json()
    assert cards["asset_type"] == "deck" and cards["status"] == "completed"

    # Summary → summary generation.
    summ = client.post(f"/workspaces/{ws}/ai/action", json={"action": "summary", "document_id": doc}, headers=headers).json()
    assert summ["asset_type"] == "summary" and summ["status"] == "completed"

    # Unknown action → 422; missing document → 404.
    assert client.post(f"/workspaces/{ws}/ai/action", json={"action": "translate", "document_id": doc}, headers=headers).status_code == 422
    assert client.post(f"/workspaces/{ws}/ai/action", json={"action": "notes", "document_id": "nope"}, headers=headers).status_code == 404


# ------------------------------------------------------------------ overview / observability
def test_overview_workspace_statistics(workspace):
    client, headers, _, ws = workspace
    _ingest(client, headers, ws)
    client.post(f"/workspaces/{ws}/search", json={"query": "architecture"}, headers=headers)  # a search
    ov = client.get(f"/workspaces/{ws}/ai/overview", headers=headers).json()
    assert ov["assets"]["documents"] == 1 and ov["assets"]["diagrams"] >= 1
    assert ov["modalities"]["vision_assets"] == 3 and ov["modalities"]["ocr_pages"] >= 1
    assert ov["pipelines"]["processed_documents"] == 1 and ov["pipelines"]["vision_analyzed"] == 1
    assert ov["activity"]["searches"] >= 1
    assert ov["ready_documents"] == 1


def test_empty_workspace_surfaces(workspace):
    client, headers, _, ws = workspace
    assert client.get(f"/workspaces/{ws}/ai/assets", headers=headers).json()["total"] == 0
    assert client.get(f"/workspaces/{ws}/ai/timeline", headers=headers).json()["items"] == []
    assert client.get(f"/workspaces/{ws}/ai/overview", headers=headers).json()["assets"]["documents"] == 0
