"""Integration tests for the Phase-6 Module-3 Verification API + agent auto-verification.

Drives verification over HTTP with the in-memory DB + the Module-1 `get_agent_services` override
(fake answer function). Covers ad-hoc verify, persistence + history + report slices, the
verify-a-stored-task path, and — crucially — that every Module-2 specialized-agent task now carries a
verification report and writes a VerificationLog.
"""

from __future__ import annotations


def _upload_pdf(client, headers, ws, name="notes.pdf"):
    r = client.post(f"/workspaces/{ws}/documents", headers=headers,
                    files=[("files", (name, b"%PDF-1.4 hello", "application/pdf"))])
    assert r.status_code == 201, r.text
    return r.json()["items"][0]["document"]["id"]


V = "/workspaces/{ws}/verification"
T = "/workspaces/{ws}/agent-tasks"

_EVIDENCE = [
    {"text": "A mutex provides mutual exclusion so only one thread enters the critical section.",
     "document_id": "d1", "score": 0.9},
    {"text": "Deadlock requires four conditions: mutual exclusion, hold and wait, no preemption, circular wait.",
     "document_id": "d1", "score": 0.85},
]


# --------------------------------------------------------------------- ad-hoc verify
def test_verify_endpoint_persists_and_reads_back(workspace):
    client, headers, _uid, ws = workspace
    answer = ("A mutex provides mutual exclusion so only one thread enters the critical section [1]. "
              "Quantum computers solve deadlock instantly.")
    r = client.post(V.format(ws=ws) + "/verify", headers=headers,
                    json={"answer": answer, "evidence": _EVIDENCE, "mode": "fast"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("verified", "warning", "failed")
    assert body["claims_total"] >= 2 and body["counts"]["unsupported"] >= 1   # the quantum claim
    assert "confidence" in body and 0.0 <= body["confidence"]["overall"] <= 1.0
    assert body["missing_evidence"]                                            # unsupported claim listed
    assert "explanations" in body and "verification_path" in body["explanations"]

    # persisted → listable + detail + slices
    hist = client.get(V.format(ws=ws), headers=headers)
    assert hist.status_code == 200 and len(hist.json()) == 1
    vid = hist.json()[0]["id"]
    detail = client.get(V.format(ws=ws) + f"/{vid}", headers=headers)
    assert detail.status_code == 200 and detail.json()["report"]["status"] == body["status"]
    for slice_ in ("confidence", "contradictions", "citations", "evidence-map", "explanation"):
        s = client.get(V.format(ws=ws) + f"/{vid}/{slice_}", headers=headers)
        assert s.status_code == 200


def test_verify_detects_conflict(workspace):
    client, headers, _uid, ws = workspace
    evidence = [{"text": "Paging is reliable and prevents fragmentation.", "document_id": "d1", "score": 0.9}]
    answer = "Paging is not reliable and it causes fragmentation."
    r = client.post(V.format(ws=ws) + "/verify", headers=headers,
                    json={"answer": answer, "evidence": evidence, "mode": "fast"})
    assert r.status_code == 200
    body = r.json()
    assert body["counts"]["conflicting"] >= 1 or body["contradictions"]
    assert body["status"] in ("warning", "failed")


def test_verify_thorough_runs_single_model_review(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(V.format(ws=ws) + "/verify", headers=headers,
                    json={"answer": "A mutex ensures mutual exclusion [1].", "evidence": _EVIDENCE,
                          "mode": "thorough"})
    assert r.status_code == 200
    # the fake answer_fn produced a model review note
    assert any("Model review" in n for n in r.json()["review_notes"])


def test_verify_no_persist(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(V.format(ws=ws) + "/verify", headers=headers,
                    json={"answer": "A mutex ensures mutual exclusion [1].", "evidence": _EVIDENCE,
                          "persist": False})
    assert r.status_code == 200
    assert client.get(V.format(ws=ws), headers=headers).json() == []


# --------------------------------------------------------------------- agent auto-verification
def test_agent_task_auto_verifies(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    run = client.post(T.format(ws=ws) + "/research", headers=headers,
                      json={"objective": "explain deadlocks"}).json()
    assert run["success"] is True
    # the task response now carries a verification report
    assert run["verification"] is not None and "status" in run["verification"]
    tid = run["task_id"]
    # and a VerificationLog is queryable by the task id
    v = client.get(V.format(ws=ws) + f"/tasks/{tid}", headers=headers)
    assert v.status_code == 200 and v.json()["execution_id"] == tid
    assert v.json()["report"]["status"] in ("verified", "warning", "failed")


def test_agent_task_verify_off(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    run = client.post(T.format(ws=ws) + "/research", headers=headers,
                      json={"objective": "explain deadlocks", "verify": "off"}).json()
    assert run["success"] is True and run["verification"] is None
    # no verification log written
    assert client.get(V.format(ws=ws), headers=headers).json() == []


def test_reverify_stored_task(workspace):
    client, headers, _uid, ws = workspace
    _upload_pdf(client, headers, ws)
    run = client.post(T.format(ws=ws) + "/writing", headers=headers,
                      json={"objective": "os overview", "doc_type": "study_guide", "verify": "off"}).json()
    tid = run["task_id"]
    r = client.post(V.format(ws=ws) + f"/tasks/{tid}/verify", headers=headers, json={"mode": "fast"})
    assert r.status_code == 200 and "confidence" in r.json()


# --------------------------------------------------------------------- misc
def test_verification_stats(workspace):
    client, headers, _uid, ws = workspace
    client.post(V.format(ws=ws) + "/verify", headers=headers,
                json={"answer": "A mutex ensures mutual exclusion [1].", "evidence": _EVIDENCE})
    s = client.get(V.format(ws=ws) + "/stats", headers=headers)
    assert s.status_code == 200 and s.json()["verifications"] >= 1


def test_verification_unknown_404(workspace):
    client, headers, _uid, ws = workspace
    assert client.get(V.format(ws=ws) + "/nope", headers=headers).status_code == 404


def test_verify_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.post(V.format(ws=ws) + "/verify", json={"answer": "x"}).status_code in (401, 403)
