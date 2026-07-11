"""Integration tests for the Multimodal Context Engineering HTTP surface (faiss-free).

Full flow: upload → Module-1 processing → Module-2 vision → Module-3 retrieval (consumed) → Module-4
context assembly (dedup → rank → budget → compress → assemble → prompt → citations) → response.
"""

from __future__ import annotations


def _seed(client, headers, ws):
    client.post(f"/workspaces/{ws}/documents",
                files=[("files", ("os.pdf", b"%PDF-1.4 fake", "application/pdf"))], headers=headers)
    doc = client.get(f"/workspaces/{ws}/documents", headers=headers).json()["items"][0]["id"]
    client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers)
    client.post(f"/workspaces/{ws}/documents/{doc}/vision", headers=headers)
    return doc


def _build(client, headers, ws, **body):
    return client.post(f"/workspaces/{ws}/context/build", json=body, headers=headers)


# ------------------------------------------------------------------ auth / scoping
def test_requires_auth(workspace):
    client, _, _, ws = workspace
    assert client.post(f"/workspaces/{ws}/context/build", json={"query": "x"}).status_code == 401


def test_foreign_workspace_404(workspace, client):
    _, _, _, ws = workspace
    reg = client.post("/auth/register", json={"email": "bob@x.com", "password": "password12", "display_name": "Bob"})
    bob = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.post(f"/workspaces/{ws}/context/build", json={"query": "x"}, headers=bob).status_code == 404


# ------------------------------------------------------------------ build
def test_build_assembles_multimodal_context(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)

    r = _build(client, headers, ws, query="explain the architecture diagram").json()
    assert r["primary_intent"] == "diagram"
    assert "diagram" in r["modalities"]
    # Adaptive assembly: the diagram block leads (primary intent).
    assert r["blocks"] and r["blocks"][0]["modality"] == "diagram"
    # Evidence carries scores + selection reasons + ranking explanation.
    item = r["blocks"][0]["items"][0]
    assert item["evidence_score"] > 0 and item["selection_reason"]
    assert "ranking_contributions" in item
    # Citations + metrics + budget present.
    assert isinstance(r["citations"], list)
    m = r["metrics"]
    assert m["retrieved"] >= 1 and m["included"] >= 1 and m["context_tokens"] > 0
    assert set(m["stage_ms"]) >= {"dedup", "rank", "budget", "assemble", "prompt"}
    assert any(b["modality"] == "diagram" for b in r["budget"])


def test_token_budget_never_exceeded(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    r = _build(client, headers, ws, query="recognized text architecture table", token_budget=300).json()
    assert r["metrics"]["context_tokens"] <= 300


def test_dedup_reduction_reported(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    r = _build(client, headers, ws, query="page recognized text").json()
    assert 0.0 <= r["metrics"]["duplicate_reduction"] <= 1.0
    assert 0.0 < r["metrics"]["compression_ratio"] <= 1.0


def test_developer_prompt_preview(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    # Non-developer build omits the raw prompt.
    plain = _build(client, headers, ws, query="architecture", developer=False).json()
    assert plain["prompt"] is None
    # Developer build (via /build) includes it.
    dev = _build(client, headers, ws, query="architecture", developer=True).json()
    assert dev["prompt"] and "LexiMind" in dev["prompt"] and "User question:" in dev["prompt"]
    # The /prompt endpoint forces developer mode.
    pv = client.post(f"/workspaces/{ws}/context/prompt", json={"query": "architecture"}, headers=headers).json()
    assert pv["prompt"] and "context" in pv and pv["metrics"]["included"] >= 0


def test_modality_scoping(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    r = _build(client, headers, ws, query="architecture", modalities=["diagram"]).json()
    assert r["modalities"] == ["diagram"]
    assert all(b["modality"] == "diagram" for b in r["blocks"])


# ------------------------------------------------------------------ observability
def test_observability(workspace):
    client, headers, _, ws = workspace
    _seed(client, headers, ws)
    _build(client, headers, ws, query="architecture diagram")
    _build(client, headers, ws, query="what is deadlock")
    obs = client.get(f"/workspaces/{ws}/context/observability", headers=headers).json()
    assert obs["builds"] >= 2
    assert "diagram" in obs["intent_usage"] or "text" in obs["intent_usage"]
    assert obs["avg_context_tokens"] >= 0 and len(obs["recent"]) >= 1


def test_empty_workspace_build(workspace):
    client, headers, _, ws = workspace
    r = _build(client, headers, ws, query="anything").json()
    assert r["metrics"]["retrieved"] == 0 and r["metrics"]["included"] == 0 and r["blocks"] == []
