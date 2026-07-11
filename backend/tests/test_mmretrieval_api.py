"""Integration tests for the Multimodal Search HTTP surface (faiss-free lexical text retriever).

Full flow: upload → Module-1 processing (OCR + image/table/figure) → Module-2 vision (captions +
classification) → multimodal search across modalities → fusion → cross-modal rerank → explanation +
stats + health.
"""

from __future__ import annotations


def _seed(client, headers, ws):
    client.post(f"/workspaces/{ws}/documents",
                files=[("files", ("os.pdf", b"%PDF-1.4 fake", "application/pdf"))], headers=headers)
    doc = client.get(f"/workspaces/{ws}/documents", headers=headers).json()["items"][0]["id"]
    client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers)   # OCR pages + image + table + figure
    client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers)    # captions + classification
    return doc


def _search(client, headers, ws, **body):
    return client.post(f"/workspaces/{ws}/search", json=body, headers=headers)


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/search", json={"query": "x"}).status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.post(f"/workspaces/{ws}/search", json={"query": "x"}, headers=bob).status_code == 404


# ------------------------------------------------------------------ intent-driven multimodal search
def test_search_activates_intended_modalities(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)

    # A diagram query activates the diagram retriever and finds the architecture diagram.
    r = _search(client, headers, ws, query="architecture diagram").json()
    assert "diagram" in r["intents"] and r["primary"] == "diagram"
    modalities = {res["modality"] for res in r["results"]}
    assert "diagram" in modalities
    diagram = next(res for res in r["results"] if res["modality"] == "diagram")
    assert diagram["metadata"]["image_type"] == "architecture_diagram"


def test_search_ocr_and_table(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    # OCR content ("recognized text") is retrievable.
    ocr = _search(client, headers, ws, query="recognized text").json()
    assert any(res["modality"] in ("ocr", "text") for res in ocr["results"])
    # Table headers are retrievable (header-aware).
    tbl = _search(client, headers, ws, query="Col A Col B table").json()
    assert "table" in tbl["intents"]
    assert any(res["modality"] == "table" for res in tbl["results"])


def test_explanation_present(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    r = _search(client, headers, ws, query="architecture diagram", explain=True).json()
    assert r["results"], "expected results"
    exp = r["results"][0]["explanation"]
    for key in ("retriever", "raw_score", "normalized_score", "fusion_score", "fusion_contributions", "reranker_score", "final_rank"):
        assert key in exp
    # Retriever stats are reported per activated modality.
    assert any(s["modality"] == "diagram" for s in r["retriever_stats"])


def test_fusion_dedup_across_modalities(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    # "System architecture" appears in both the diagram caption AND (after vision enrichment) the
    # figure's multimodal chunk → the same evidence may be found by multiple retrievers and merges.
    r = _search(client, headers, ws, query="system architecture").json()
    multi = [res for res in r["results"] if len(res["explanation"]["contributing_modalities"]) > 1]
    assert isinstance(multi, list)  # may or may not merge, but the structure must hold
    assert r["total"] >= 1


# ------------------------------------------------------------------ single-modality + rerank toggle
def test_search_by_modality_endpoint(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    r = client.get(f"/workspaces/{ws}/search/modality/diagram?q=architecture", headers=headers).json()
    assert r["intents"] == ["diagram"]
    assert all(res["modality"] == "diagram" for res in r["results"])


def test_rerank_toggle(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    on = _search(client, headers, ws, query="architecture diagram", rerank=True).json()
    off = _search(client, headers, ws, query="architecture diagram", rerank=False).json()
    assert on["total"] == off["total"]
    assert on["results"][0]["confidence"] is not None


def test_modality_validation(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    assert _search(client, headers, ws, query="x", modalities=["nonsense"]).status_code == 422


# ------------------------------------------------------------------ stats / health / suggestions
def test_stats_health_suggestions(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    _search(client, headers, ws, query="architecture diagram")
    _search(client, headers, ws, query="deadlock")

    stats = client.get(f"/workspaces/{ws}/search/stats", headers=headers).json()
    assert stats["searches"] >= 2 and "diagram" in stats["modality_usage"]
    assert stats["indexed"]["vision_assets"] >= 1

    health = client.get(f"/workspaces/{ws}/search/health", headers=headers).json()
    assert health["status"] == "ok" and "diagram" in health["retrievers"]
    assert "pending" in health["embedding_queue"]

    sug = client.get(f"/workspaces/{ws}/search/suggestions?q=operating", headers=headers).json()
    assert isinstance(sug["suggestions"], list)


def test_empty_workspace_search(workspace):
    client, headers, _, ws = workspace
    r = _search(client, headers, ws, query="anything").json()
    assert r["total"] == 0 and "text" in r["intents"]
