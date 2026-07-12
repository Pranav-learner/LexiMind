"""Integration tests for the Phase-7 Module-3 Graph Reasoning & Explainable AI API.

Drives reasoning over HTTP with the in-memory DB: build a graph (Module-1 /extract), then reason
(multi-hop paths + inferred relationships + confidence + verification + explanation), preview, root-cause,
dependency analysis, inferred-edge listing, stats, logs — plus agent integration (graph_reason tool).
No LLM/faiss runs.
"""

from __future__ import annotations


def _seed(client, headers, ws):
    text = ("Paging is part of Virtual Memory. Virtual Memory is part of Memory Management. "
            "Memory Management is part of the Operating System. React uses JavaScript. "
            "JavaScript depends on Node.js. FastAPI depends on Pydantic. FastAPI uses Python.")
    assert client.post(f"/workspaces/{ws}/graph/extract", headers=headers, json={"text": text}).status_code == 200


R = "/workspaces/{ws}/reasoning"


# --------------------------------------------------------------------- reason
def test_reason_pipeline(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    r = client.post(R.format(ws=ws) + "/reason", headers=headers,
                    json={"query": "how does the Operating System relate to Virtual Memory", "hops": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["seeds"] and body["paths"]
    assert body["confidence"] and 0.0 <= body["confidence"]["overall"] <= 1.0
    assert body["verification"]["graph_consistency"] is True
    assert body["explanation"]["reasoning_pipeline"] and body["context_text"]
    assert "recognition_ms" in body["timings"] and "paths_ms" in body["timings"]
    # a transitive inference was derived (part_of ∘ part_of → part_of)
    assert any(i["rel_type"] == "part_of" and i["inferred"] for i in body["inferences"])

    # persisted: reasoning log + inferred edges (status=inferred, separate from extracted)
    logs = client.get(R.format(ws=ws) + "/logs", headers=headers)
    assert logs.status_code == 200 and len(logs.json()) >= 1
    inferred = client.get(R.format(ws=ws) + "/inferred", headers=headers)
    assert inferred.status_code == 200 and len(inferred.json()) >= 1
    assert all(x["status"] == "inferred" for x in inferred.json())


def test_reason_cache_hit(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    client.post(R.format(ws=ws) + "/reason", headers=headers, json={"query": "React", "hops": 3})
    r2 = client.post(R.format(ws=ws) + "/reason", headers=headers, json={"query": "React", "hops": 3})
    assert r2.json()["cache_hit"] is True


def test_preview_does_not_persist(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    r = client.post(R.format(ws=ws) + "/preview", headers=headers,
                    json={"query": "Operating System", "hops": 3})
    assert r.status_code == 200 and "paths" in r.json()
    assert client.get(R.format(ws=ws) + "/logs", headers=headers).json() == []   # preview writes no log


# --------------------------------------------------------------------- root cause / dependency
def test_root_cause_analysis(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    r = client.post(R.format(ws=ws) + "/root-cause", headers=headers,
                    json={"query": "what does React depend on"})
    assert r.status_code == 200
    # React uses JavaScript → depends on Node.js → Node.js is a root cause
    assert any(rc["entity"] == "Node.js" for rc in r.json()["root_causes"])


def test_dependency_analysis_by_entity(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    ents = client.get(f"/workspaces/{ws}/graph/entities?query=fastapi", headers=headers).json()
    fastapi_id = next(e["id"] for e in ents if e["canonical_name"] == "FastAPI")
    r = client.get(R.format(ws=ws) + f"/entities/{fastapi_id}/dependencies", headers=headers)
    assert r.status_code == 200 and r.json()["entity"]["name"] == "FastAPI"
    assert r.json()["dependencies"] or r.json()["root_causes"]


# --------------------------------------------------------------------- explain / stats
def test_explain_endpoint(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    r = client.post(R.format(ws=ws) + "/explain", headers=headers,
                    json={"query": "Operating System memory management"})
    assert r.status_code == 200
    ex = r.json()["explanation"]
    assert "reasoning_paths" in ex and "why_conclusion" in ex


def test_stats(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    client.post(R.format(ws=ws) + "/reason", headers=headers, json={"query": "React"})
    s = client.get(R.format(ws=ws) + "/stats", headers=headers)
    assert s.status_code == 200 and s.json()["reasonings"] >= 1 and "cache" in s.json()


# --------------------------------------------------------------------- agent integration (Step 10)
def test_research_agent_uses_graph_reason(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    tools = {t["name"] for t in client.get(f"/workspaces/{ws}/agent/tools", headers=headers).json()}
    assert "graph_reason" in tools
    r = client.post(f"/workspaces/{ws}/agent-tasks/research", headers=headers,
                    json={"objective": "How does the Operating System manage Virtual Memory?"})
    assert r.status_code == 200 and r.json()["success"] is True
    assert "graph_reason" in (r.json()["plan"].get("tools") or [])


# --------------------------------------------------------------------- misc
def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.post(R.format(ws=ws) + "/reason", json={"query": "x"}).status_code in (401, 403)


def test_unknown_entity_dependencies_404(workspace):
    client, headers, _uid, ws = workspace
    assert client.get(R.format(ws=ws) + "/entities/nope/dependencies", headers=headers).status_code == 404
