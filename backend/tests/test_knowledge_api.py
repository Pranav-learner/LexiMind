"""Integration tests for the Phase-7 Module-1 Knowledge Graph API.

Drives graph construction over HTTP with the in-memory DB + the synchronous InlineRunner (conftest):
  ad-hoc /extract, document/workspace build (reusing ingestion chunk text), entity/relationship search,
  entity detail, stats, validation, logs, and agent contribution — all writing a GraphConstructionLog.
No LLM/faiss/torch runs.
"""

from __future__ import annotations


def _upload_pdf(client, headers, ws, name="notes.pdf"):
    r = client.post(f"/workspaces/{ws}/documents", headers=headers,
                    files=[("files", (name, b"%PDF-1.4 hello", "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["document"]["id"]


def _process(client, headers, ws, doc):
    r = client.post(f"/workspaces/{ws}/documents/{doc}/process", headers=headers, json={})
    assert r.status_code in (200, 202), r.text


G = "/workspaces/{ws}/graph"


# --------------------------------------------------------------------- ad-hoc extraction (developer)
def test_extract_endpoint_builds_graph(workspace):
    client, headers, _uid, ws = workspace
    text = ("React is built on JavaScript and uses a virtual DOM. A Large Language Model (LLM) depends "
            "on PyTorch. GPT is a Large Language Model developed by OpenAI.")
    r = client.post(G.format(ws=ws) + "/extract", headers=headers, json={"text": text})
    assert r.status_code == 200, r.text
    log = r.json()
    assert log["status"] == "completed" and log["entities_created"] >= 5
    assert log["relationships_created"] >= 3 and log["report"]["validation"]["ok"] in (True, False)

    # entities searchable + typed
    ents = client.get(G.format(ws=ws) + "/entities", headers=headers).json()
    by_name = {e["canonical_name"]: e for e in ents}
    assert "React" in by_name and by_name["React"]["entity_type"] == "framework"
    assert "Large Language Model" in by_name and "LLM" in by_name["Large Language Model"]["aliases"]

    # relationships typed + directed with named endpoints
    rels = client.get(G.format(ws=ws) + "/relationships", headers=headers).json()
    triples = {(r_["source_name"], r_["rel_type"], r_["target_name"]) for r_ in rels}
    assert ("Large Language Model", "depends_on", "PyTorch") in triples

    # entity detail includes its relationships
    llm_id = by_name["Large Language Model"]["id"]
    detail = client.get(G.format(ws=ws) + f"/entities/{llm_id}", headers=headers)
    assert detail.status_code == 200 and detail.json()["relationships"]


def test_extract_is_incremental_and_dedupes(workspace):
    client, headers, _uid, ws = workspace
    client.post(G.format(ws=ws) + "/extract", headers=headers,
                json={"text": "A Large Language Model (LLM) depends on PyTorch."})
    r2 = client.post(G.format(ws=ws) + "/extract", headers=headers,
                     json={"text": "LLM systems also use PyTorch heavily."})
    assert r2.json()["entities_merged"] >= 1   # LLM + PyTorch merged, not duplicated
    ents = client.get(G.format(ws=ws) + "/entities?query=large", headers=headers).json()
    llm = [e for e in ents if e["canonical_name"] == "Large Language Model"]
    assert len(llm) == 1 and llm[0]["mention_count"] >= 2


# --------------------------------------------------------------------- document / workspace build (reuses chunks)
def test_document_build_reuses_ingested_chunks(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_pdf(client, headers, ws)
    _process(client, headers, ws, doc)   # ingestion inline → MultimodalChunk rows exist
    r = client.post(G.format(ws=ws) + f"/documents/{doc}/build", headers=headers, json={})
    assert r.status_code == 200, r.text
    log = r.json()
    assert log["status"] == "completed" and log["scope"] == "document"
    assert log["sources_processed"] >= 1   # read the ingested chunk text (no re-processing)


def test_workspace_build_and_logs(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_pdf(client, headers, ws)
    _process(client, headers, ws, doc)
    r = client.post(G.format(ws=ws) + "/build", headers=headers, json={})
    assert r.status_code == 200 and r.json()["scope"] == "workspace"

    logs = client.get(G.format(ws=ws) + "/logs", headers=headers)
    assert logs.status_code == 200 and len(logs.json()) >= 1
    log_id = logs.json()[0]["id"]
    detail = client.get(G.format(ws=ws) + f"/logs/{log_id}", headers=headers)
    assert detail.status_code == 200 and "report" in detail.json()


# --------------------------------------------------------------------- stats / validation / filters
def test_stats_and_validation(workspace):
    client, headers, _uid, ws = workspace
    client.post(G.format(ws=ws) + "/extract", headers=headers,
                json={"text": "Python uses FastAPI. FastAPI depends on Pydantic and Starlette."})
    stats = client.get(G.format(ws=ws) + "/stats", headers=headers)
    assert stats.status_code == 200 and stats.json()["entities"] >= 2
    assert "language" in stats.json()["entity_types"] or "framework" in stats.json()["entity_types"]

    val = client.get(G.format(ws=ws) + "/validate", headers=headers)
    assert val.status_code == 200 and "ok" in val.json()


def test_entity_type_filter(workspace):
    client, headers, _uid, ws = workspace
    client.post(G.format(ws=ws) + "/extract", headers=headers,
                json={"text": "Python and JavaScript are languages. React is a framework."})
    langs = client.get(G.format(ws=ws) + "/entities?type=language", headers=headers).json()
    assert langs and all(e["entity_type"] == "language" for e in langs)


# --------------------------------------------------------------------- agent contribution (Step 16)
def test_agent_contributes_to_graph(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    # a research task with contribute_graph=True automatically feeds its objective/answer into the graph
    # through the SAME extraction pipeline (the run_task hook, wired in Phase-7 M1).
    r = client.post(f"/workspaces/{ws}/agent-tasks/research", headers=headers,
                    json={"objective": "How does React use JavaScript and depend on Node.js and PyTorch?",
                          "contribute_graph": True})
    assert r.status_code == 200, r.text
    # the graph now holds entities the agent mentioned (no separate extraction call)
    names = {e["canonical_name"] for e in client.get(G.format(ws=ws) + "/entities", headers=headers).json()}
    assert {"React", "JavaScript", "Node.js"} & names
    # and it was logged as an agent-scoped contribution
    scopes = {l["scope"] for l in client.get(G.format(ws=ws) + "/logs", headers=headers).json()}
    assert "agent" in scopes


# --------------------------------------------------------------------- misc
def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.post(G.format(ws=ws) + "/extract", json={"text": "x"}).status_code in (401, 403)


def test_unknown_entity_404(workspace):
    client, headers, _uid, ws = workspace
    assert client.get(G.format(ws=ws) + "/entities/nope", headers=headers).status_code == 404
