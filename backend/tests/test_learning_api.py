"""Integration tests for the Phase-8 Module-4 Continuous Learning API.

Drives the platform over HTTP: submit feedback, seed a verification failure, run a learning cycle, review
(approve/reject) governed recommendations, build a failure dataset, and read the improvement report. Verifies
the safety invariant — recommendations enter as `pending` and only a human review changes their status.
"""

from __future__ import annotations

L = "/workspaces/{ws}/learning"


def _seed_verification_failure(client, headers, ws, uid):
    # a direct DB seed via the app's session is not exposed over HTTP, so drive failure signals through
    # feedback (the analyzer treats negative feedback + corrections as failures too).
    for i in range(3):
        client.post(L.format(ws=ws) + "/feedback", headers=headers,
                    json={"target_type": "answer", "target_id": f"a{i}", "kind": "thumbs_down",
                          "comment": "hallucinated the dates"})
    client.post(L.format(ws=ws) + "/feedback", headers=headers,
                json={"target_type": "agent", "target_id": "ag1", "kind": "thumbs_down", "comment": "agent failed"})
    client.post(L.format(ws=ws) + "/feedback", headers=headers,
                json={"target_type": "answer", "target_id": "a9", "kind": "correction",
                      "comment": "what is X?", "correction": "X is the answer."})


# --------------------------------------------------------------------- feedback
def test_submit_and_summarize_feedback(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(L.format(ws=ws) + "/feedback", headers=headers,
                    json={"target_type": "answer", "target_id": "a1", "kind": "star", "rating": 2})
    assert r.status_code == 200 and r.json()["sentiment"] == "negative"

    up = client.post(L.format(ws=ws) + "/feedback", headers=headers,
                     json={"target_type": "answer", "target_id": "a2", "kind": "thumbs_up"})
    assert up.status_code == 200 and up.json()["sentiment"] == "positive"

    hist = client.get(L.format(ws=ws) + "/feedback", headers=headers)
    assert hist.status_code == 200 and len(hist.json()) == 2
    neg = client.get(L.format(ws=ws) + "/feedback?sentiment=negative", headers=headers)
    assert all(f["sentiment"] == "negative" for f in neg.json())

    summ = client.get(L.format(ws=ws) + "/feedback/summary", headers=headers)
    assert summ.status_code == 200 and summ.json()["total"] == 2 and "negative_rate" in summ.json()


def test_bad_feedback_422(workspace):
    client, headers, _uid, ws = workspace
    assert client.post(L.format(ws=ws) + "/feedback", headers=headers,
                       json={"kind": "bogus"}).status_code == 422
    assert client.post(L.format(ws=ws) + "/feedback", headers=headers,
                       json={"kind": "star", "rating": 9}).status_code == 422


# --------------------------------------------------------------------- learning cycle + governed review
def test_cycle_generates_governed_recommendations(workspace):
    client, headers, uid, ws = workspace
    _seed_verification_failure(client, headers, ws, uid)

    insights = client.get(L.format(ws=ws) + "/insights", headers=headers)
    assert insights.status_code == 200 and insights.json()["total_failures"] >= 3
    assert insights.json()["clusters"]

    cycle = client.post(L.format(ws=ws) + "/cycle", headers=headers)
    assert cycle.status_code == 200, cycle.text
    body = cycle.json()
    assert body["recommendations_generated"] >= 1 and body["cycle_id"] and body["affected_components"]

    # every recommendation enters as PENDING (never auto-applied)
    pending = client.get(L.format(ws=ws) + "/recommendations?status=pending", headers=headers)
    assert pending.status_code == 200 and len(pending.json()) >= 1
    rec = pending.json()[0]
    assert rec["status"] == "pending" and rec["reason"] and rec["expected_impact"] and rec["affected_components"]

    # detail
    detail = client.get(L.format(ws=ws) + f"/recommendations/{rec['id']}", headers=headers)
    assert detail.status_code == 200 and "evidence" in detail.json()

    # approve → auditable status transition
    appr = client.post(L.format(ws=ws) + f"/recommendations/{rec['id']}/approve", headers=headers,
                       json={"note": "valid — will schedule"})
    assert appr.status_code == 200 and appr.json()["status"] == "approved"
    assert appr.json()["reviewer"] == uid and appr.json()["reviewed_at"]

    # reject another if present
    remaining = client.get(L.format(ws=ws) + "/recommendations?status=pending", headers=headers).json()
    if remaining:
        rej = client.post(L.format(ws=ws) + f"/recommendations/{remaining[0]['id']}/reject", headers=headers,
                         json={"note": "not now"})
        assert rej.status_code == 200 and rej.json()["status"] == "rejected"


def test_unknown_recommendation_404(workspace):
    client, headers, _uid, ws = workspace
    assert client.get(L.format(ws=ws) + "/recommendations/nope", headers=headers).status_code == 404


# --------------------------------------------------------------------- dataset builder + report
def test_dataset_and_report(workspace):
    client, headers, uid, ws = workspace
    _seed_verification_failure(client, headers, ws, uid)
    client.post(L.format(ws=ws) + "/cycle", headers=headers)

    ds = client.post(L.format(ws=ws) + "/dataset", headers=headers, json={"name": "regressions"})
    assert ds.status_code == 200 and ds.json()["created"] and ds.json()["item_count"] >= 1

    report = client.get(L.format(ws=ws) + "/report", headers=headers)
    assert report.status_code == 200 and "recommendation_status" in report.json() and report.json()["cycles"]

    dash = client.get(L.format(ws=ws) + "/dashboard", headers=headers)
    assert dash.status_code == 200
    assert {"feedback", "insights", "review", "pending_recommendations"} <= set(dash.json().keys())


def test_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.get(L.format(ws=ws) + "/dashboard").status_code in (401, 403)
