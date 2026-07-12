"""Integration tests for the Phase-7 Module-2 Semantic Memory & Graph Retrieval API.

Drives graph retrieval over HTTP with the in-memory DB: build a graph (Module-1 /extract), then resolve
entities, traverse, retrieve knowledge, fuse (hybrid), inspect neighborhoods, sync, and log — plus the
agent integration (research agent auto-uses graph_search). No LLM/faiss index runs.
"""

from __future__ import annotations


def _seed_graph(client, headers, ws):
    text = ("React is built on JavaScript and uses a virtual DOM. React depends on Node.js. "
            "A Large Language Model (LLM) depends on PyTorch. GPT is a Large Language Model developed by OpenAI.")
    r = client.post(f"/workspaces/{ws}/graph/extract", headers=headers, json={"text": text})
    assert r.status_code == 200, r.text


M = "/workspaces/{ws}/memory"


# --------------------------------------------------------------------- recognition
def test_recognize_query_entities(workspace):
    client, headers, _uid, ws = workspace
    _seed_graph(client, headers, ws)
    r = client.post(M.format(ws=ws) + "/recognize", headers=headers,
                    json={"query": "how does React use JavaScript?"})
    assert r.status_code == 200
    names = {e["canonical_name"] for e in r.json()}
    assert "React" in names and "JavaScript" in names


# --------------------------------------------------------------------- retrieval
def test_graph_retrieval_pipeline(workspace):
    client, headers, _uid, ws = workspace
    _seed_graph(client, headers, ws)
    r = client.post(M.format(ws=ws) + "/retrieve", headers=headers,
                    json={"query": "what does React use and depend on", "hops": 2, "limit": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "graph" and body["seed_count"] >= 1
    assert body["neighborhood"]["nodes"] >= 2 and body["neighborhood"]["edges"] >= 1
    assert body["hits"] and body["context_text"] and body["citations"]
    kinds = {h["kind"] for h in body["hits"]}
    assert {"entity", "relationship"} & kinds
    assert "recognition_ms" in body["timings"] and "traversal_ms" in body["timings"]

    # a repeat query hits the neighborhood cache
    r2 = client.post(M.format(ws=ws) + "/retrieve", headers=headers,
                     json={"query": "what does React use and depend on", "hops": 2, "limit": 10})
    assert r2.json()["cache_hit"] is True

    # persisted to the semantic-memory log
    logs = client.get(M.format(ws=ws) + "/logs", headers=headers)
    assert logs.status_code == 200 and len(logs.json()) >= 2


def test_hybrid_retrieval_fuses_graph_and_vectors(workspace):
    client, headers, _uid, ws = workspace
    _seed_graph(client, headers, ws)
    r = client.post(M.format(ws=ws) + "/retrieve", headers=headers,
                    json={"query": "React", "hops": 2, "hybrid": True})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "hybrid" and body["fused"]
    assert "graph" in {f["modality"] for f in body["fused"]}   # graph is a fused modality


def test_dfs_strategy_and_hop_limit(workspace):
    client, headers, _uid, ws = workspace
    _seed_graph(client, headers, ws)
    r = client.post(M.format(ws=ws) + "/retrieve", headers=headers,
                    json={"query": "React", "hops": 1, "strategy": "dfs"})
    assert r.status_code == 200 and r.json()["neighborhood"]["max_hop"] <= 1


# --------------------------------------------------------------------- neighborhood + sync + stats
def test_entity_neighborhood_explorer(workspace):
    client, headers, _uid, ws = workspace
    _seed_graph(client, headers, ws)
    ents = client.get(f"/workspaces/{ws}/graph/entities?query=react", headers=headers).json()
    react_id = next(e["id"] for e in ents if e["canonical_name"] == "React")
    r = client.get(M.format(ws=ws) + f"/entities/{react_id}/neighborhood?hops=1", headers=headers)
    assert r.status_code == 200
    assert r.json()["seed"]["name"] == "React" and r.json()["nodes"] and r.json()["edges"]


def test_sync_invalidates_cache_and_stats(workspace):
    client, headers, _uid, ws = workspace
    _seed_graph(client, headers, ws)
    client.post(M.format(ws=ws) + "/retrieve", headers=headers, json={"query": "React"})
    s = client.post(M.format(ws=ws) + "/sync", headers=headers, json={})
    assert s.status_code == 200 and s.json()["synced"] is True

    stats = client.get(M.format(ws=ws) + "/stats", headers=headers)
    assert stats.status_code == 200 and "graph" in stats.json() and "cache" in stats.json()


def test_unknown_entity_neighborhood_404(workspace):
    client, headers, _uid, ws = workspace
    assert client.get(M.format(ws=ws) + "/entities/nope/neighborhood", headers=headers).status_code == 404


def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.post(M.format(ws=ws) + "/retrieve", json={"query": "x"}).status_code in (401, 403)


# --------------------------------------------------------------------- agent integration (Step 15)
def test_research_agent_uses_graph_search(workspace):
    client, headers, _uid, ws = workspace
    _seed_graph(client, headers, ws)
    # graph_search is now a registered tool + a default research-agent tool
    tools = {t["name"] for t in client.get(f"/workspaces/{ws}/agent/tools", headers=headers).json()}
    assert "graph_search" in tools
    r = client.post(f"/workspaces/{ws}/agent-tasks/research", headers=headers,
                    json={"objective": "How does React use JavaScript and Node.js?"})
    assert r.status_code == 200 and r.json()["success"] is True
    # the research plan invoked graph_search among its tools (Semantic Memory as a retrieval provider)
    assert "graph_search" in (r.json()["plan"].get("tools") or [])
