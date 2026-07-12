"""Integration tests for the Phase-7 Module-4 Interactive Knowledge Workspace API.

Drives the full knowledge workspace over HTTP with the in-memory DB + faked graph-chat answer_fn
(conftest): build a graph, then overview / graph explorer / entity + relationship detail / unified
search / timeline / analytics / AI graph chat (reuses ChatService) / controlled editing / activity log.
No LLM/faiss runs.
"""

from __future__ import annotations


def _seed(client, headers, ws):
    text = ("React is built on JavaScript and uses a virtual DOM. React depends on Node.js. "
            "JavaScript depends on Node.js. FastAPI depends on Pydantic and uses Python.")
    assert client.post(f"/workspaces/{ws}/graph/extract", headers=headers, json={"text": text}).status_code == 200


K = "/workspaces/{ws}/knowledge-workspace"


# --------------------------------------------------------------------- overview + explorer
def test_overview_and_graph_view(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    ov = client.get(K.format(ws=ws) + "/overview", headers=headers)
    assert ov.status_code == 200 and ov.json()["entities"] >= 3 and ov.json()["top_concepts"]

    gv = client.get(K.format(ws=ws) + "/graph", headers=headers)
    assert gv.status_code == 200 and gv.json()["node_count"] >= 3 and gv.json()["edge_count"] >= 1
    react = next(n for n in gv.json()["nodes"] if n["name"] == "React")

    # lazy neighborhood expansion around a seed
    exp = client.get(K.format(ws=ws) + f"/graph?seed={react['id']}&hops=1", headers=headers)
    assert exp.status_code == 200 and exp.json()["seed"] == react["id"]


def test_entity_and_relationship_detail(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    ents = client.get(f"/workspaces/{ws}/graph/entities?query=react", headers=headers).json()
    react_id = next(e["id"] for e in ents if e["canonical_name"] == "React")
    det = client.get(K.format(ws=ws) + f"/entities/{react_id}", headers=headers)
    assert det.status_code == 200 and det.json()["relationships"] and "reasoning" in det.json()

    rels = client.get(f"/workspaces/{ws}/graph/relationships", headers=headers).json()
    rel_id = rels[0]["id"]
    rd = client.get(K.format(ws=ws) + f"/relationships/{rel_id}", headers=headers)
    assert rd.status_code == 200 and "why_connected" in rd.json() and "evidence" in rd.json()


# --------------------------------------------------------------------- unified search
def test_unified_search(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    r = client.post(K.format(ws=ws) + "/search", headers=headers, json={"query": "what does React use"})
    assert r.status_code == 200 and "hits" in r.json() and "citations" in r.json()
    assert any(e["name"] == "React" for e in r.json()["entities"])


# --------------------------------------------------------------------- timeline + analytics
def test_timeline_and_analytics(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    tl = client.get(K.format(ws=ws) + "/timeline", headers=headers)
    assert tl.status_code == 200 and any(e["type"] == "entity_created" for e in tl.json())
    an = client.get(K.format(ws=ws) + "/analytics", headers=headers)
    assert an.status_code == 200 and an.json()["top_connected"] and "growth" in an.json()


# --------------------------------------------------------------------- AI graph chat (reuses ChatService)
def test_ai_graph_chat(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    r = client.post(K.format(ws=ws) + "/chat", headers=headers,
                    json={"content": "What does React depend on?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conversation_id"] and body["answer"] and body["grounded"] is True
    # the conversation is a normal chat conversation (reused ChatService) — continue it
    r2 = client.post(K.format(ws=ws) + "/chat", headers=headers,
                     json={"content": "and what does that depend on?", "conversation_id": body["conversation_id"]})
    assert r2.status_code == 200 and r2.json()["conversation_id"] == body["conversation_id"]


# --------------------------------------------------------------------- controlled editing
def test_rename_and_merge_and_create_relationship(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    ents = client.get(f"/workspaces/{ws}/graph/entities", headers=headers).json()
    react = next(e for e in ents if e["canonical_name"] == "React")
    node = next(e for e in ents if e["canonical_name"] == "Node.js")

    # rename
    ren = client.post(K.format(ws=ws) + "/edit", headers=headers,
                      json={"op": "rename_entity", "params": {"entity_id": react["id"], "new_name": "React.js"}})
    assert ren.status_code == 200 and ren.json()["entity"]["canonical_name"] == "React.js"
    assert "React" in ren.json()["entity"]["aliases"] and ren.json()["entity"]["version"] == 2

    # create a new relationship
    cr = client.post(K.format(ws=ws) + "/edit", headers=headers,
                     json={"op": "create_relationship", "params": {"source_id": react["id"],
                           "target_id": node["id"], "rel_type": "implements"}})
    assert cr.status_code == 200 and cr.json()["status"] == "active"

    # activity was logged
    act = client.get(K.format(ws=ws) + "/activity", headers=headers)
    assert act.status_code == 200 and any(a["activity_type"] == "graph_edit" for a in act.json())


def test_approve_inferred_relationship(workspace):
    client, headers, _uid, ws = workspace
    _seed(client, headers, ws)
    # produce inferred relationships via the reasoning engine
    client.post(f"/workspaces/{ws}/reasoning/reason", headers=headers, json={"query": "React Node.js", "hops": 3})
    inferred = client.get(f"/workspaces/{ws}/reasoning/inferred", headers=headers).json()
    if inferred:
        rid = inferred[0]["id"]
        ap = client.post(K.format(ws=ws) + "/edit", headers=headers,
                         json={"op": "approve_relationship", "params": {"rel_id": rid}})
        assert ap.status_code == 200 and ap.json()["status"] == "active"


def test_edit_bad_op_422(workspace):
    client, headers, _uid, ws = workspace
    assert client.post(K.format(ws=ws) + "/edit", headers=headers,
                       json={"op": "nuke_graph", "params": {}}).status_code == 422


# --------------------------------------------------------------------- misc
def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.get(K.format(ws=ws) + "/overview").status_code in (401, 403)


def test_unknown_entity_404(workspace):
    client, headers, _uid, ws = workspace
    assert client.get(K.format(ws=ws) + "/entities/nope", headers=headers).status_code == 404
