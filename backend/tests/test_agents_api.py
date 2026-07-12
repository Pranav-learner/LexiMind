"""Integration tests for the Agent Framework API (Phase 6, Module 1).

Drives the full agentic loop over HTTP with the in-memory DB + media InlineRunner + FakeMediaEngine +
FAKED answer + inline generation runners (conftest):
  run → plan → tool selection → tool execution (reusing real retrieval/generation services) →
  PromptPackage → single answer pathway → AgentExecutionLog → history/graph/retry/cancel.
No LLM/ollama/faiss/torch runs.
"""

from __future__ import annotations


def _upload_media(client, headers, ws, *, name="CS101 Deadlocks Lecture.mp4"):
    r = client.post(f"/workspaces/{ws}/media", headers=headers,
                    files=[("file", (name, b"\x00\x00\x00fakevideo", "video/mp4"))])
    assert r.status_code == 201, r.text
    return r.json()["document_id"]


def _upload_pdf(client, headers, ws):
    r = client.post(f"/workspaces/{ws}/documents", headers=headers,
                    files=[("files", ("notes.pdf", b"%PDF-1.4 hello", "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["document"]["id"]


# --------------------------------------------------------------------- discovery
def test_tool_and_agent_discovery(workspace):
    client, headers, _uid, ws = workspace
    tools = client.get(f"/workspaces/{ws}/agent/tools", headers=headers)
    assert tools.status_code == 200
    names = {t["name"] for t in tools.json()}
    assert {"workspace_search", "temporal_search", "generate_summary"} <= names
    one = client.get(f"/workspaces/{ws}/agent/tools/workspace_search", headers=headers)
    assert one.status_code == 200 and one.json()["category"] == "search"

    agents = client.get(f"/workspaces/{ws}/agent/agents", headers=headers)
    assert agents.status_code == 200
    by = {a["name"]: a for a in agents.json()}
    assert by["workspace_agent"]["implemented"] is True
    assert by["research_agent"]["status"] == "planned"


def test_unknown_tool_404(workspace):
    client, headers, _uid, ws = workspace
    assert client.get(f"/workspaces/{ws}/agent/tools/nope", headers=headers).status_code == 404


# --------------------------------------------------------------------- planner preview (no execution)
def test_planner_preview_does_not_execute(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(f"/workspaces/{ws}/agent/plan", headers=headers, json={"query": "summarize the notes"})
    assert r.status_code == 200
    body = r.json()
    assert body["requires_tools"] is True
    assert [n["tool"] for n in body["graph"]["nodes"]] == ["generate_summary"]
    # a preview writes NO execution log
    assert client.get(f"/workspaces/{ws}/agent/executions", headers=headers).json() == []


# --------------------------------------------------------------------- run (retrieve → answer)
def test_run_agent_qa_flow(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/agent/run", headers=headers, json={"query": "what is in the notes?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["phase"] == "done"
    assert body["answer"]                                    # faked single-answer pathway produced text
    assert [n["tool"] for n in body["plan"]["graph"]["nodes"]] == ["workspace_search"]
    assert body["tool_count"] >= 1
    assert body["prompt_package"]["rendered_preview"]
    assert "planner_ms" in body["timings"] and "llm_ms" in body["timings"]
    # tool nodes carry execution telemetry
    node = body["plan"]["graph"]["nodes"][0]
    assert node["status"] in ("ok", "failed", "skipped")
    assert any(ev["event"] == "plan" for ev in body["timeline"])


def test_run_agent_media_uses_temporal_tool(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/agent/run", headers=headers,
                    json={"query": "what did the speaker say in the lecture?", "document_id": doc})
    assert r.status_code == 200, r.text
    tools = [n["tool"] for n in r.json()["plan"]["graph"]["nodes"]]
    assert "temporal_search" in tools and "workspace_search" in tools


def test_run_agent_generation_tool_creates_asset(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_pdf(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/agent/run", headers=headers,
                    json={"query": "make flashcards", "document_id": doc})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [n["tool"] for n in body["plan"]["graph"]["nodes"]] == ["generate_flashcards"]
    tr = body["tool_results"][0]
    assert tr["ok"] is True and tr["output"]["asset_type"] == "deck"
    # the deck exists through the EXISTING flashcards API
    deck_id = tr["output"]["asset_id"]
    assert client.get(f"/workspaces/{ws}/decks/{deck_id}", headers=headers).status_code == 200


# --------------------------------------------------------------------- permissions
def test_run_respects_allowed_tools_and_permissions(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    # deny the generate permission → a generation request's tool is denied (never executed)
    r = client.post(f"/workspaces/{ws}/agent/run", headers=headers,
                    json={"query": "summarize this", "granted_permissions": ["search"]})
    assert r.status_code == 200
    node = r.json()["plan"]["graph"]["nodes"][0]
    assert node["tool"] == "generate_summary" and node["status"] == "denied"


# --------------------------------------------------------------------- observability + history
def test_execution_is_logged_and_listable(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    run = client.post(f"/workspaces/{ws}/agent/run", headers=headers, json={"query": "explain the notes"}).json()
    exec_id = run["execution_id"]

    hist = client.get(f"/workspaces/{ws}/agent/executions", headers=headers)
    assert hist.status_code == 200 and any(e["id"] == exec_id for e in hist.json())

    detail = client.get(f"/workspaces/{ws}/agent/executions/{exec_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["graph"]["graph"]["nodes"]          # serialized execution graph persisted
    assert detail.json()["timeline"]

    graph = client.get(f"/workspaces/{ws}/agent/executions/{exec_id}/graph", headers=headers)
    assert graph.status_code == 200 and "graph" in graph.json()

    stats = client.get(f"/workspaces/{ws}/agent/stats", headers=headers)
    assert stats.status_code == 200 and stats.json()["executions"] >= 1


def test_retry_creates_new_execution(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    first = client.post(f"/workspaces/{ws}/agent/run", headers=headers, json={"query": "what is here"}).json()
    retry = client.post(f"/workspaces/{ws}/agent/executions/{first['execution_id']}/retry", headers=headers)
    assert retry.status_code == 200
    assert retry.json()["execution_id"] != first["execution_id"]


def test_cancel_completed_execution_conflicts(workspace):
    client, headers, _uid, ws = workspace
    run = client.post(f"/workspaces/{ws}/agent/run", headers=headers, json={"query": "hi"}).json()
    # synchronous runs are terminal on return → cancel is a 409
    r = client.post(f"/workspaces/{ws}/agent/executions/{run['execution_id']}/cancel", headers=headers)
    assert r.status_code == 409


def test_run_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.post(f"/workspaces/{ws}/agent/run", json={"query": "x"}).status_code in (401, 403)
