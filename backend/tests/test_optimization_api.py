"""Integration tests for the Phase-8 Module-3 Optimization API.

Drives the platform over HTTP with the in-memory DB + faked answer function: preview a plan (no execution),
run an optimized query through the REAL pipeline, verify cache short-circuit on the second run, inspect
cost/quality analysis + history, and manage per-workspace policy. No LLM/faiss runs.
"""

from __future__ import annotations

import pytest

from app.optimization.cache_intel import ANSWER_CACHE


@pytest.fixture(autouse=True)
def _clear_answer_cache():
    ANSWER_CACHE._store.clear()
    ANSWER_CACHE.hits = 0
    ANSWER_CACHE.misses = 0
    yield


def _upload_pdf(client, headers, ws):
    r = client.post(f"/workspaces/{ws}/documents", headers=headers,
                    files=[("files", ("notes.pdf", b"%PDF-1.4 deadlocks and concurrency", "application/pdf"))])
    assert r.status_code == 201, r.text


O = "/workspaces/{ws}/optimization"


# --------------------------------------------------------------------- preview / recommend (no execution)
def test_preview_and_recommend(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(O.format(ws=ws) + "/preview", headers=headers,
                    json={"question": "x"} if False else {"query": "what is a deadlock?", "policy": "lowest_cost"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["policy"] == "lowest_cost" and body["model"]["name"] and body["candidates"]
    assert "retrieval" in body and "context" in body and "prompt" in body
    assert body["estimated_cost"] < body["baseline_cost"]

    m = client.post(O.format(ws=ws) + "/recommend/model", headers=headers,
                    json={"query": "compare and analyze tradeoffs across systems", "policy": "highest_quality"})
    assert m.status_code == 200 and m.json()["selected"]["quality"] >= 0.7

    p = client.post(O.format(ws=ws) + "/recommend/pipeline", headers=headers, json={"query": "summarize"})
    assert p.status_code == 200 and "retrieval" in p.json() and "recommendations" in p.json()


def test_unknown_policy_422(workspace):
    client, headers, _uid, ws = workspace
    # schema pattern rejects it at 422
    r = client.post(O.format(ws=ws) + "/preview", headers=headers, json={"query": "x", "policy": "bogus"})
    assert r.status_code == 422


# --------------------------------------------------------------------- optimized execution + cache
def test_run_optimized_then_cache_hit(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    body = {"query": "what is a deadlock?", "policy": "balanced"}

    r1 = client.post(O.format(ws=ws) + "/run", headers=headers, json=body)
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["run_id"] and j1["result"]["cache_used"] is False
    assert "answer" in j1["result"] and "plan" in j1 and j1["savings"] >= 0

    # second identical run → answer cache short-circuits the whole pipeline
    r2 = client.post(O.format(ws=ws) + "/run", headers=headers, json=body)
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["result"]["cache_used"] is True and j2["plan"]["cache_decision"] == "hit"
    assert j2["result"]["actual_cost"] == 0.0 and j2["savings"] == 1.0

    history = client.get(O.format(ws=ws) + "/history", headers=headers)
    assert history.status_code == 200 and len(history.json()) == 2
    assert any(h["cache_used"] for h in history.json())


# --------------------------------------------------------------------- cost / quality / cache / dashboard
def test_cost_and_quality_analysis(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    client.post(O.format(ws=ws) + "/run", headers=headers, json={"query": "explain deadlocks", "policy": "balanced"})

    cost = client.get(O.format(ws=ws) + "/cost", headers=headers)
    assert cost.status_code == 200 and "optimization" in cost.json() and "top_cost_sources" in cost.json()

    qvc = client.get(O.format(ws=ws) + "/quality-vs-cost", headers=headers)
    assert qvc.status_code == 200 and qvc.json()["count"] >= 1
    assert "cost" in qvc.json()["points"][0] and "quality" in qvc.json()["points"][0]

    cache = client.get(O.format(ws=ws) + "/cache", headers=headers)
    assert cache.status_code == 200 and "answer" in cache.json()["layers"]

    dash = client.get(O.format(ws=ws) + "/dashboard", headers=headers)
    assert dash.status_code == 200
    assert {"policy", "cost_analysis", "cache", "recent_runs"} <= set(dash.json().keys())


# --------------------------------------------------------------------- policy management
def test_workspace_policy_persists_and_applies(workspace):
    client, headers, _uid, ws = workspace
    # default
    assert client.get(O.format(ws=ws) + "/policy", headers=headers).json()["current"] == "balanced"
    # set to lowest_cost
    s = client.put(O.format(ws=ws) + "/policy", headers=headers, json={"policy": "lowest_cost"})
    assert s.status_code == 200 and s.json()["current"] == "lowest_cost"
    assert client.get(O.format(ws=ws) + "/policy", headers=headers).json()["current"] == "lowest_cost"
    # a preview with NO explicit policy now uses the persisted workspace policy
    p = client.post(O.format(ws=ws) + "/preview", headers=headers, json={"query": "define X"})
    assert p.json()["policy"] == "lowest_cost"


def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.get(O.format(ws=ws) + "/dashboard").status_code in (401, 403)
