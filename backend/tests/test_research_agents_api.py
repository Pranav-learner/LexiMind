"""Integration tests for the Phase-6 Module-2 specialized-agent task API.

Drives the full pipeline over HTTP with the in-memory DB + FAKED single-answer function + inline
generation runners (conftest `get_agent_services` override):
  request → AgentTaskService → specialized agent → framework executor → real retrieval/generation
  services → PromptPackage → single answer pathway → StructuredOutput → AgentTaskLog → history/export/
  retry/cancel/workflow.
No LLM/ollama/faiss/torch runs.
"""

from __future__ import annotations


def _upload_pdf(client, headers, ws, name="notes.pdf"):
    r = client.post(f"/workspaces/{ws}/documents", headers=headers,
                    files=[("files", (name, b"%PDF-1.4 hello", "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["document"]["id"]


def _upload_media(client, headers, ws, name="Lecture.mp4"):
    r = client.post(f"/workspaces/{ws}/media", headers=headers,
                    files=[("file", (name, b"\x00\x00\x00fakevideo", "video/mp4"))])
    assert r.status_code == 201, r.text
    return r.json()["document_id"]


B = "/workspaces/{ws}/agent-tasks"


# --------------------------------------------------------------------- discovery
def test_agent_and_workflow_discovery(workspace):
    client, headers, _uid, ws = workspace
    agents = client.get(B.format(ws=ws) + "/agents", headers=headers)
    assert agents.status_code == 200 and set(agents.json()) >= {"research", "writing", "comparison", "study"}
    wfs = client.get(B.format(ws=ws) + "/workflows", headers=headers)
    assert wfs.status_code == 200
    assert {w["name"] for w in wfs.json()} >= {"research_and_write", "study_pack"}


# --------------------------------------------------------------------- research
def test_run_research_task(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    r = client.post(B.format(ws=ws) + "/research", headers=headers,
                    json={"objective": "explain deadlocks and recovery"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["phase"] == "done"
    assert body["agent"] == "research_agent" and body["task_type"] == "research"
    assert body["output"]["markdown"] and "Report" in body["output"]["markdown"]
    assert "planner_ms" in body["timings"] and body["plan"]["subquestions"]

    # persisted + listable + detail + export
    tid = body["task_id"]
    hist = client.get(B.format(ws=ws), headers=headers)
    assert hist.status_code == 200 and any(t["id"] == tid for t in hist.json())
    detail = client.get(B.format(ws=ws) + f"/{tid}", headers=headers)
    assert detail.status_code == 200 and detail.json()["output"]["markdown"]
    assert detail.json()["steps"]
    exp = client.get(B.format(ws=ws) + f"/{tid}/export", headers=headers)
    assert exp.status_code == 200 and exp.json()["format"] == "markdown" and exp.json()["content"]
    exp_json = client.get(B.format(ws=ws) + f"/{tid}/export?format=json", headers=headers)
    assert exp_json.status_code == 200 and exp_json.json()["format"] == "json"


# --------------------------------------------------------------------- writing
def test_run_writing_task_doc_type(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    r = client.post(B.format(ws=ws) + "/writing", headers=headers,
                    json={"objective": "operating systems overview", "doc_type": "study_guide"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["agent"] == "writing_agent"
    assert "Study Guide" in body["output"]["title"]


# --------------------------------------------------------------------- comparison
def test_run_comparison_task_two_documents(workspace):
    client, headers, _uid, ws = workspace
    d1 = _upload_pdf(client, headers, ws, name="a.pdf")
    d2 = _upload_pdf(client, headers, ws, name="b.pdf")
    r = client.post(B.format(ws=ws) + "/comparison", headers=headers,
                    json={"objective": "compare the two documents", "document_ids": [d1, d2]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["agent"] == "comparison_agent"
    assert body["plan"]["targets"] and len(body["plan"]["targets"]) == 2


def test_comparison_needs_two_targets(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(B.format(ws=ws) + "/comparison", headers=headers,
                    json={"objective": "just one thing"})
    assert r.status_code == 200
    assert r.json()["success"] is False and r.json()["phase"] == "failed"


# --------------------------------------------------------------------- study (reuses generation services)
def test_run_study_task_creates_flashcards(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_pdf(client, headers, ws)
    r = client.post(B.format(ws=ws) + "/study", headers=headers,
                    json={"objective": "prepare for the exam", "document_ids": [doc],
                          "deliverables": ["flashcards", "learning_path"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["agent"] == "study_agent"
    created = body["plan"]["created_assets"]
    assert created and created[0]["asset_type"] == "deck"
    # the deck exists through the EXISTING flashcards API (real service, inline runner)
    deck_id = created[0]["asset_id"]
    assert client.get(f"/workspaces/{ws}/decks/{deck_id}", headers=headers).status_code == 200


def test_study_generation_denied_without_permission(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_pdf(client, headers, ws)
    r = client.post(B.format(ws=ws) + "/study", headers=headers,
                    json={"objective": "cards", "document_ids": [doc], "deliverables": ["flashcards"],
                          "granted_permissions": ["search"]})   # no generate/write
    assert r.status_code == 200
    # task still completes but the generation tool was denied → no asset created
    assert r.json()["plan"]["created_assets"] == []


# --------------------------------------------------------------------- workflow
def test_run_workflow_research_and_write(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    r = client.post(B.format(ws=ws) + "/workflows/research_and_write/run", headers=headers,
                    json={"objective": "summarize the workspace knowledge"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow"] == "research_and_write" and len(body["steps"]) == 2
    assert [s["task_type"] for s in body["steps"]] == ["research", "writing"]
    assert body["final_task_id"]
    # both steps persisted as task logs tagged with the workflow
    hist = client.get(B.format(ws=ws), headers=headers).json()
    assert sum(1 for t in hist if t["workflow"] == "research_and_write") == 2


# --------------------------------------------------------------------- preview / retry / cancel
def test_preview_does_not_execute(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(B.format(ws=ws) + "/preview", headers=headers,
                    json={"task_type": "research", "objective": "cache coherence and MESI"})
    assert r.status_code == 200 and r.json()["plan"]["subquestions"]
    assert client.get(B.format(ws=ws), headers=headers).json() == []   # nothing persisted


def test_retry_creates_new_task(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    first = client.post(B.format(ws=ws) + "/research", headers=headers,
                        json={"objective": "what is here"}).json()
    retry = client.post(B.format(ws=ws) + f"/{first['task_id']}/retry", headers=headers)
    assert retry.status_code == 200 and retry.json()["task_id"] != first["task_id"]


def test_cancel_completed_task_conflicts(workspace):
    client, headers, _uid, ws = workspace
    run = client.post(B.format(ws=ws) + "/research", headers=headers, json={"objective": "x"}).json()
    r = client.post(B.format(ws=ws) + f"/{run['task_id']}/cancel", headers=headers)
    assert r.status_code == 409


def test_stats_endpoint(workspace):
    client, headers, _uid, ws = workspace
    client.post(B.format(ws=ws) + "/research", headers=headers, json={"objective": "a"})
    s = client.get(B.format(ws=ws) + "/stats", headers=headers)
    assert s.status_code == 200 and s.json()["tasks"] >= 1


def test_task_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.post(B.format(ws=ws) + "/research", json={"objective": "x"}).status_code in (401, 403)


def test_unknown_workflow_404(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(B.format(ws=ws) + "/workflows/nope/run", headers=headers, json={"objective": "x"})
    assert r.status_code == 404
