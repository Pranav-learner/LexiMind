"""Integration tests for the Phase-8 Module-1 AI Evaluation & Benchmarking API.

Drives the framework over HTTP with the in-memory DB + faked answer function (conftest get_agent_services):
golden dataset → run the REAL pipeline → metric collection → EvaluationRunLog → regression → comparison →
dashboard. No LLM/faiss runs.
"""

from __future__ import annotations


E = "/workspaces/{ws}/evaluation"


def _dataset(client, headers, ws, name="golden"):
    r = client.post(E.format(ws=ws) + "/datasets", headers=headers, json={
        "name": name, "description": "test set",
        "items": [
            {"question": "what is a mutex?", "expected_answer": "mutual exclusion",
             "relevant_document_ids": ["doc_x"], "relevant_chunk_ids": ["doc_x:1"], "difficulty": "easy"},
            {"question": "explain deadlocks", "expected_answer": "circular wait",
             "relevant_document_ids": ["doc_y"], "difficulty": "hard"},
        ]})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --------------------------------------------------------------------- datasets
def test_dataset_lifecycle(workspace):
    client, headers, _uid, ws = workspace
    ds_id = _dataset(client, headers, ws)
    lst = client.get(E.format(ws=ws) + "/datasets", headers=headers)
    assert lst.status_code == 200 and any(d["id"] == ds_id for d in lst.json())
    d = next(d for d in lst.json() if d["id"] == ds_id)
    assert d["item_count"] == 2 and d["difficulty_distribution"]["easy"] == 1

    exp = client.get(E.format(ws=ws) + f"/datasets/{ds_id}/export", headers=headers)
    assert exp.status_code == 200 and len(exp.json()["items"]) == 2
    # round-trip import
    imp = client.post(E.format(ws=ws) + "/datasets/import", headers=headers, json=exp.json())
    assert imp.status_code == 200 and imp.json()["item_count"] == 2


def test_dataset_validation_422(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(E.format(ws=ws) + "/datasets", headers=headers,
                    json={"name": "bad", "items": [{"question": ""}]})
    assert r.status_code == 422


def test_pipelines_listed(workspace):
    client, headers, _uid, ws = workspace
    r = client.get(E.format(ws=ws) + "/pipelines", headers=headers)
    assert r.status_code == 200
    assert {p["name"] for p in r.json()} >= {"workspace_retrieval", "graph_retrieval", "answer"}


# --------------------------------------------------------------------- run benchmark (real pipeline)
def test_run_retrieval_benchmark(workspace):
    client, headers, _uid, ws = workspace
    ds_id = _dataset(client, headers, ws)
    r = client.post(E.format(ws=ws) + "/run", headers=headers,
                    json={"dataset_id": ds_id, "pipeline": "workspace_retrieval"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and body["item_count"] == 2
    assert "metrics" in body and body["gate"] is not None
    assert body["regression_status"] == "none"      # first run → no baseline

    # a second run gets an auto-baseline + regression report
    r2 = client.post(E.format(ws=ws) + "/run", headers=headers,
                     json={"dataset_id": ds_id, "pipeline": "workspace_retrieval"})
    assert r2.status_code == 200 and r2.json()["baseline_run_id"] == body["id"]
    assert r2.json()["regression_status"] in ("stable", "improved", "regressed")


def test_run_answer_pipeline_with_verification(workspace):
    client, headers, _uid, ws = workspace
    ds_id = _dataset(client, headers, ws)
    r = client.post(E.format(ws=ws) + "/run", headers=headers,
                    json={"dataset_id": ds_id, "pipeline": "answer"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item_count"] == 2 and body["items"]
    # the answer pipeline produced answers (fake answer_fn) + verification metrics
    assert any(it["output"]["answer"] for it in body["items"])


def test_run_with_ci_gate_and_judge(workspace):
    client, headers, _uid, ws = workspace
    ds_id = _dataset(client, headers, ws)
    r = client.post(E.format(ws=ws) + "/run", headers=headers,
                    json={"dataset_id": ds_id, "pipeline": "answer", "use_judge": True,
                          "thresholds": {"latency_ms": 1_000_000}})
    assert r.status_code == 200
    assert r.json()["judge_used"] is True and r.json()["gate"]["passed"] is True


# --------------------------------------------------------------------- history / regression / compare / dashboard
def test_history_regression_compare_dashboard(workspace):
    client, headers, _uid, ws = workspace
    ds_id = _dataset(client, headers, ws)
    a = client.post(E.format(ws=ws) + "/run", headers=headers,
                    json={"dataset_id": ds_id, "pipeline": "workspace_retrieval", "label": "A"}).json()
    b = client.post(E.format(ws=ws) + "/run", headers=headers,
                    json={"dataset_id": ds_id, "pipeline": "graph_retrieval", "label": "B"}).json()

    hist = client.get(E.format(ws=ws) + "/runs", headers=headers)
    assert hist.status_code == 200 and len(hist.json()) >= 2

    detail = client.get(E.format(ws=ws) + f"/runs/{a['id']}", headers=headers)
    assert detail.status_code == 200 and "report" in detail.json()

    comp = client.post(E.format(ws=ws) + "/compare", headers=headers,
                       json={"a_run_id": a["id"], "b_run_id": b["id"]})
    assert comp.status_code == 200 and "winner" in comp.json()["comparison"]

    reg = client.post(E.format(ws=ws) + f"/runs/{a['id']}/regression", headers=headers,
                      json={"baseline_run_id": b["id"]})
    assert reg.status_code == 200 and "deltas" in reg.json()

    dash = client.get(E.format(ws=ws) + "/dashboard", headers=headers)
    assert dash.status_code == 200 and dash.json()["total_runs"] >= 2 and "cache" in dash.json()


# --------------------------------------------------------------------- misc
def test_run_unknown_dataset_404(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(E.format(ws=ws) + "/run", headers=headers,
                    json={"dataset_id": "nope", "pipeline": "workspace_retrieval"})
    assert r.status_code == 404


def test_run_unknown_pipeline_404(workspace):
    client, headers, _uid, ws = workspace
    ds_id = _dataset(client, headers, ws)
    r = client.post(E.format(ws=ws) + "/run", headers=headers,
                    json={"dataset_id": ds_id, "pipeline": "quantum_retrieval"})
    assert r.status_code == 404


def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.get(E.format(ws=ws) + "/datasets").status_code in (401, 403)
