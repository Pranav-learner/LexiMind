"""Integration tests for Temporal Intelligence persistence + Temporal Retrieval & Context API.

Full lifecycle over HTTP with the in-memory DB + media InlineRunner + FakeMediaEngine (conftest):
upload media → synchronous processing → temporal-intelligence derivation → temporal search → timeline/
speaker/timestamp queries → prompt preview → explanation → citations → stats/health. No A/V or LLM.
"""

from __future__ import annotations


def _upload_media(client, headers, ws, *, name="CS101 Deadlocks Lecture.mp4"):
    r = client.post(f"/workspaces/{ws}/media", headers=headers,
                    files=[("file", (name, b"\x00\x00\x00fakevideo", "video/mp4"))])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["job"]["status"] == "completed"
    return body["document_id"]


# --------------------------------------------------------------------- tintel persistence
def test_derive_persists_chapters_topics_events(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/media/{doc}/temporal-intelligence/derive", headers=headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chapters"] >= 1 and body["events"] >= 1

    chapters = client.get(f"/workspaces/{ws}/media/{doc}/chapters", headers=headers)
    assert chapters.status_code == 200
    assert len(chapters.json()) == body["chapters"]
    assert chapters.json()[0]["source"] == "derived"     # canonical baseline, Module 2 enriches

    events = client.get(f"/workspaces/{ws}/media/{doc}/events", headers=headers)
    assert events.status_code == 200
    types = {e["event_type"] for e in events.json()}
    assert "chapter_start" in types
    ts = [e["timestamp_ms"] for e in events.json()]
    assert ts == sorted(ts)


def test_events_filtered_by_type(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.get(f"/workspaces/{ws}/media/{doc}/events?event_type=speaker_change", headers=headers)
    assert r.status_code == 200
    assert all(e["event_type"] == "speaker_change" for e in r.json())


def test_chapters_auto_derive_on_read(workspace):
    # No explicit derive call — reading chapters should ensure_derived transparently.
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.get(f"/workspaces/{ws}/media/{doc}/chapters", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_derive_conflict_when_not_processed(workspace):
    # A non-media document can't derive temporal intelligence.
    client, headers, _uid, ws = workspace
    up = client.post(f"/workspaces/{ws}/documents", headers=headers,
                     files=[("files", ("notes.pdf", b"%PDF-1.4 x", "application/pdf"))])
    pdf_doc = up.json()["items"][0]["document"]["id"]
    r = client.post(f"/workspaces/{ws}/media/{pdf_doc}/temporal-intelligence/derive", headers=headers, json={})
    assert r.status_code == 409


# --------------------------------------------------------------------- temporal search
def test_temporal_search_returns_timestamped_results(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/temporal/search", headers=headers,
                    json={"query": "transcript segment", "top_k": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    assert "transcript" in body["intents"]
    res = body["results"][0]
    # every result preserves exact timestamps + provenance (Step 8)
    assert "start_ms" in res and "end_ms" in res and res["timespan"]
    assert res["final_rank"] == 1
    assert res["explanation"]["fusion_score"] >= 0
    # timeline-aware context + prompt + citations were built
    assert body["prompt"] and "Question:" in body["prompt"]
    assert body["citations"] and body["citations"][0]["timespan"]
    assert body["context_blocks"]


def test_temporal_search_timestamp_query_sets_time_filter(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/temporal/search", headers=headers,
                    json={"query": "what was said at 0:05", "top_k": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["time_filter"] is not None
    assert body["time_filter"]["anchor_ms"] == 5000
    assert "timestamp" in body["intents"]


def test_temporal_search_speaker_query(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/temporal/search", headers=headers,
                    json={"query": "what did speaker say", "top_k": 5})
    assert r.status_code == 200
    assert "speaker" in r.json()["intents"]


def test_timeline_and_speaker_convenience_routes(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    tl = client.get(f"/workspaces/{ws}/temporal/timeline?q=speaker", headers=headers)
    assert tl.status_code == 200
    assert "event" in tl.json()["intents"]
    sp = client.get(f"/workspaces/{ws}/temporal/speakers?q=speaker", headers=headers)
    assert sp.status_code == 200
    assert sp.json()["intents"] == ["speaker"]


def test_temporal_search_scoped_to_document(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/temporal/search", headers=headers,
                    json={"query": "transcript", "document_id": doc, "top_k": 5})
    assert r.status_code == 200
    assert all(res["document_id"] == doc for res in r.json()["results"])


def test_unknown_modality_rejected(workspace):
    client, headers, _uid, ws = workspace
    _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/temporal/search", headers=headers,
                    json={"query": "x", "modalities": ["bogus"]})
    assert r.status_code == 422


# --------------------------------------------------------------------- prompt preview / explain
def test_prompt_preview(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/temporal/prompt", headers=headers,
                    json={"query": "explain transcript segment at 0:20"})
    assert r.status_code == 200
    body = r.json()
    assert body["query_type"] in ("timestamp", "transcript", "topic", "speaker", "timeline", "scene")
    assert body["prompt"] and body["system_prompt"]
    assert body["token_estimate"] > 0


def test_explain_exposes_analysis_and_scores(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/temporal/explain", headers=headers,
                    json={"query": "what did the speaker say about transcript at 0:10"})
    assert r.status_code == 200
    body = r.json()
    assert "keywords" in body["analysis"] and "weights" in body["analysis"]
    assert body["analysis"]["primary"]
    if body["results"]:
        assert "fusion_contributions" in body["results"][0]["explanation"]


# --------------------------------------------------------------------- stats / health
def test_stats_and_health(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    client.post(f"/workspaces/{ws}/temporal/search", headers=headers, json={"query": "transcript"})
    stats = client.get(f"/workspaces/{ws}/temporal/stats", headers=headers)
    assert stats.status_code == 200
    assert stats.json()["searches"] >= 1
    assert stats.json()["indexed"]["transcript_segments"] >= 1

    health = client.get(f"/workspaces/{ws}/temporal/health", headers=headers)
    assert health.status_code == 200
    assert "transcript" in health.json()["retrievers"]
    assert health.json()["status"] == "ok"


def test_temporal_search_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    r = client.post(f"/workspaces/{ws}/temporal/search", json={"query": "x"})
    assert r.status_code in (401, 403)
