"""Integration tests for the Phase-8 Module-2 Observability API.

Drives the observability platform over HTTP with the in-memory DB + faked answer function: run an
instrumented traced query (real retrieval→answer→verify with spans), then inspect the trace, the unified
telemetry feed, metrics, cost, health, and configurable alerts. No LLM/faiss runs.
"""

from __future__ import annotations


def _upload_pdf(client, headers, ws):
    r = client.post(f"/workspaces/{ws}/documents", headers=headers,
                    files=[("files", ("notes.pdf", b"%PDF-1.4 hello", "application/pdf"))])
    assert r.status_code == 201, r.text


O = "/workspaces/{ws}/observability"


# --------------------------------------------------------------------- distributed trace (instrumented pipeline)
def test_traced_query_produces_distributed_trace(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    r = client.post(O.format(ws=ws) + "/trace-query", headers=headers,
                    json={"question": "what is in the notes?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trace_id"] and body["answer"]
    # a full parent-child trace: retrieval → graph_retrieval → context → answer → verification
    names = {s["name"] for s in body["spans"]}
    assert {"retrieval", "context", "answer", "verification"} <= names
    assert body["waterfall"] and body["span_count"] >= 4
    assert body["token_usage"] >= 0

    # trace is listable + fetchable
    traces = client.get(O.format(ws=ws) + "/traces", headers=headers)
    assert traces.status_code == 200 and any(t["id"] == body["trace_id"] for t in traces.json())
    detail = client.get(O.format(ws=ws) + f"/traces/{body['trace_id']}", headers=headers)
    assert detail.status_code == 200 and detail.json()["spans"]


def test_unknown_trace_404(workspace):
    client, headers, _uid, ws = workspace
    assert client.get(O.format(ws=ws) + "/traces/nope", headers=headers).status_code == 404


# --------------------------------------------------------------------- unified telemetry + metrics + cost + health
def test_unified_telemetry_and_metrics(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    client.post(O.format(ws=ws) + "/trace-query", headers=headers, json={"question": "q1"})
    # produce telemetry in OTHER modules too (agent task → agent_task log; verification is inside it)
    client.post(f"/workspaces/{ws}/agent-tasks/research", headers=headers, json={"objective": "explain deadlocks"})

    events = client.get(O.format(ws=ws) + "/events", headers=headers)
    assert events.status_code == 200
    sources = {e["source"] for e in events.json()}
    assert "trace" in sources and ("agent_task" in sources or "verification" in sources)   # UNIFIED, not re-logged

    m = client.get(O.format(ws=ws) + "/metrics", headers=headers)
    assert m.status_code == 200 and m.json()["requests"] >= 1 and "latency_ms" in m.json()
    assert "by_source" in m.json()

    cost = client.get(O.format(ws=ws) + "/cost", headers=headers)
    assert cost.status_code == 200 and "total_tokens" in cost.json() and "by_source" in cost.json()

    health = client.get(O.format(ws=ws) + "/health", headers=headers)
    assert health.status_code == 200 and health.json()["checks"]["database"]["status"] == "ok"


def test_events_source_filter(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    client.post(O.format(ws=ws) + "/trace-query", headers=headers, json={"question": "q"})
    r = client.get(O.format(ws=ws) + "/events?source=trace", headers=headers)
    assert r.status_code == 200 and all(e["source"] == "trace" for e in r.json())


# --------------------------------------------------------------------- alerts
def test_alert_rules_and_evaluation(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    client.post(O.format(ws=ws) + "/trace-query", headers=headers, json={"question": "q"})

    # create an aggressive custom rule that WILL fire (latency > 0)
    rule = client.post(O.format(ws=ws) + "/alerts/rules", headers=headers,
                       json={"name": "any latency", "metric": "p95_latency_ms", "comparator": "gt",
                             "threshold": 0.0, "severity": "info"})
    assert rule.status_code == 200
    rules = client.get(O.format(ws=ws) + "/alerts/rules", headers=headers)
    assert rules.status_code == 200 and any(r["id"] == rule.json()["id"] for r in rules.json())

    ev = client.post(O.format(ws=ws) + "/alerts/evaluate", headers=headers)
    assert ev.status_code == 200 and ev.json()["fired_count"] >= 1
    hist = client.get(O.format(ws=ws) + "/alerts", headers=headers)
    assert hist.status_code == 200 and len(hist.json()) >= 1

    d = client.delete(O.format(ws=ws) + f"/alerts/rules/{rule.json()['id']}", headers=headers)
    assert d.status_code == 200


# --------------------------------------------------------------------- dashboard
def test_dashboard(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    client.post(O.format(ws=ws) + "/trace-query", headers=headers, json={"question": "q"})
    d = client.get(O.format(ws=ws) + "/dashboard", headers=headers)
    assert d.status_code == 200
    body = d.json()
    assert "metrics" in body and "cost" in body and "health" in body and "recent_traces" in body


def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.get(O.format(ws=ws) + "/dashboard").status_code in (401, 403)
