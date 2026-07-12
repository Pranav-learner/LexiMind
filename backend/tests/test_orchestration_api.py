"""Integration tests for the Phase-6 Module-4 Multi-Agent Orchestration API.

Drives the full pipeline over HTTP with the in-memory DB + the Module-1 `get_agent_services` override
(fake answer + inline runners):
  objective → planner → task graph → specialized agents (real per-agent pathway) → shared context →
  aggregation (ONE answer_fn call) → final verification → OrchestrationExecutionLog.
No LLM/ollama/faiss/torch runs.
"""

from __future__ import annotations


def _upload_pdf(client, headers, ws, name="notes.pdf"):
    r = client.post(f"/workspaces/{ws}/documents", headers=headers,
                    files=[("files", (name, b"%PDF-1.4 hello", "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["document"]["id"]


O = "/workspaces/{ws}/orchestration"


# --------------------------------------------------------------------- plan preview
def test_plan_decomposes_without_executing(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(O.format(ws=ws) + "/plan", headers=headers,
                    json={"objective": "Compare the papers and write a study guide",
                          "document_ids": ["d1", "d2"]})
    assert r.status_code == 200, r.text
    ids = [n["id"] for n in r.json()["graph"]["nodes"]]
    assert "research" in ids and "comparison" in ids and "writing" in ids
    assert client.get(O.format(ws=ws), headers=headers).json() == []   # nothing persisted


# --------------------------------------------------------------------- run (auto-decomposed)
def test_run_workflow_end_to_end(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    r = client.post(O.format(ws=ws) + "/run", headers=headers,
                    json={"objective": "Research memory management and write a report"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("completed", "partial")
    assert body["orchestration_id"].startswith("orc_")
    # the graph ran research → writing → verification
    node_ids = [n["id"] for n in body["graph"]["nodes"]]
    assert "research" in node_ids and "writing" in node_ids
    # ONE aggregation answer + a unified deliverable + final verification
    assert body["answer"] and body["output"]["markdown"]
    assert body["final_verification"] and "status" in body["final_verification"]
    assert body["timeline"] and body["agents_used"]
    # each agent node produced an AgentTaskLog through the REUSED per-agent pathway
    task_hist = client.get(f"/workspaces/{ws}/agent-tasks", headers=headers).json()
    assert len(task_hist) >= 2

    # persisted + detail + graph + timeline
    oid = body["orchestration_id"]
    hist = client.get(O.format(ws=ws), headers=headers)
    assert hist.status_code == 200 and any(o["id"] == oid for o in hist.json())
    detail = client.get(O.format(ws=ws) + f"/{oid}", headers=headers)
    assert detail.status_code == 200 and detail.json()["output"]["markdown"]
    assert detail.json()["node_results"]
    assert client.get(O.format(ws=ws) + f"/{oid}/graph", headers=headers).status_code == 200
    assert client.get(O.format(ws=ws) + f"/{oid}/timeline", headers=headers).status_code == 200


def test_run_template_compare_and_report(workspace):
    client, headers, _uid, ws = workspace
    d1 = _upload_pdf(client, headers, ws, "a.pdf")
    d2 = _upload_pdf(client, headers, ws, "b.pdf")
    r = client.post(O.format(ws=ws) + "/run", headers=headers,
                    json={"objective": "Compare the two documents", "document_ids": [d1, d2],
                          "workflow": "compare_and_report"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow"] == "compare_and_report"
    node_ids = [n["id"] for n in body["graph"]["nodes"]]
    assert "comparison" in node_ids
    assert body["status"] in ("completed", "partial")


def test_run_custom_graph(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    graph = {"nodes": [
        {"id": "r", "agent": "research"},
        {"id": "w", "agent": "writing", "depends_on": ["r"], "forward_evidence": True,
         "params": {"doc_type": "executive_summary"}},
    ]}
    r = client.post(O.format(ws=ws) + "/run", headers=headers,
                    json={"objective": "Summarize the workspace", "graph": graph})
    assert r.status_code == 200, r.text
    assert [n["id"] for n in r.json()["graph"]["nodes"]] == ["r", "w"]


# --------------------------------------------------------------------- governance
def test_governance_rejects_cyclic_custom_graph(workspace):
    client, headers, _uid, ws = workspace
    graph = {"nodes": [{"id": "a", "agent": "research", "depends_on": ["b"]},
                       {"id": "b", "agent": "writing", "depends_on": ["a"]}]}
    r = client.post(O.format(ws=ws) + "/run", headers=headers,
                    json={"objective": "x", "graph": graph})
    assert r.status_code == 422


def test_governance_rejects_unknown_agent(workspace):
    client, headers, _uid, ws = workspace
    graph = {"nodes": [{"id": "a", "agent": "malware"}]}
    r = client.post(O.format(ws=ws) + "/run", headers=headers, json={"objective": "x", "graph": graph})
    assert r.status_code == 422


# --------------------------------------------------------------------- templates / stats / lifecycle
def test_templates_listed(workspace):
    client, headers, _uid, ws = workspace
    r = client.get(O.format(ws=ws) + "/templates", headers=headers)
    assert r.status_code == 200
    assert {t["name"] for t in r.json()} >= {"research_report", "compare_and_report", "study_pipeline"}


def test_stats_and_retry_and_cancel(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    run = client.post(O.format(ws=ws) + "/run", headers=headers,
                      json={"objective": "Research and write a brief"}).json()
    oid = run["orchestration_id"]

    s = client.get(O.format(ws=ws) + "/stats", headers=headers)
    assert s.status_code == 200 and s.json()["orchestrations"] >= 1

    retry = client.post(O.format(ws=ws) + f"/{oid}/retry", headers=headers)
    assert retry.status_code == 200 and retry.json()["orchestration_id"] != oid

    # synchronous runs are terminal → cancel conflicts
    assert client.post(O.format(ws=ws) + f"/{oid}/cancel", headers=headers).status_code == 409


def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.post(O.format(ws=ws) + "/run", json={"objective": "x"}).status_code in (401, 403)


def test_unknown_template_404(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(O.format(ws=ws) + "/run", headers=headers,
                    json={"objective": "x", "workflow": "does_not_exist"})
    assert r.status_code == 404
