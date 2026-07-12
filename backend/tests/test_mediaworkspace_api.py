"""Integration tests for the Audio & Video AI Workspace (Phase 5, Module 4) — the capstone.

Drives the full product flow over HTTP with the in-memory DB + media InlineRunner + FakeMediaEngine +
a FAKED LLM answer (conftest): upload media → process → overview/library → unified timeline →
playback meta → media AI chat (reusing the chat pipeline, temporal-grounded, timestamp citations) →
knowledge-asset actions (reusing summaries/notes/flashcards) → unified search → observability. No A/V
or LLM runs.
"""

from __future__ import annotations


def _upload_media(client, headers, ws, *, name="CS101 Deadlocks Lecture.mp4"):
    r = client.post(f"/workspaces/{ws}/media", headers=headers,
                    files=[("file", (name, b"\x00\x00\x00fakevideo", "video/mp4"))])
    assert r.status_code == 201, r.text
    assert r.json()["job"]["status"] == "completed"
    return r.json()["document_id"]


# --------------------------------------------------------------------- overview / library
def test_overview_aggregates_media_and_temporal(workspace):
    client, headers, _uid, ws = workspace
    _upload_media(client, headers, ws)
    r = client.get(f"/workspaces/{ws}/media-ai/overview", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recordings"] == 1 and body["video"] == 1
    assert body["transcript_segments"] >= 1 and body["speakers"] >= 1
    assert body["total_duration_ms"] == 60_000


def test_library_lists_recordings_with_intelligence_flag(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    # trigger derivation so intelligence_ready flips true
    client.get(f"/workspaces/{ws}/media-ai/{doc}/timeline", headers=headers)
    r = client.get(f"/workspaces/{ws}/media-ai/library", headers=headers)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["document_id"] == doc
    assert item["media_kind"] == "video"
    assert item["intelligence_ready"] is True
    assert item["speaker_count"] >= 1


# --------------------------------------------------------------------- unified timeline / playback
def test_unified_timeline_merges_lanes(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.get(f"/workspaces/{ws}/media-ai/{doc}/timeline", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration_ms"] == 60_000
    lanes = set(body["lanes"])
    assert {"chapters", "events", "speakers", "scenes"} <= lanes
    # ordered by start time; every item carries a timespan
    starts = [i["start_ms"] for i in body["items"]]
    assert starts == sorted(starts)
    assert all(i["timespan"] for i in body["items"])


def test_playback_meta(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.get(f"/workspaces/{ws}/media-ai/{doc}/playback", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["media_kind"] == "video"
    assert body["duration_ms"] == 60_000
    assert body["media_url"].endswith(f"/documents/{doc}/file")
    assert body["speakers"] >= 1


# --------------------------------------------------------------------- media AI chat (reuse chat pipeline)
def test_media_chat_is_temporal_grounded_with_timestamp_citations(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/media-ai/chat", headers=headers,
                    json={"content": "what is in the transcript?", "document_id": doc})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["grounded"] is True
    assert body["answer"]                                  # faked LLM produced an answer
    assert body["conversation_id"]
    assert body["citations"], "expected timestamp-preserving citations"
    cit = body["citations"][0]
    assert "start_ms" in cit and cit["timespan"]
    assert body["assistant_message_id"]


def test_media_chat_persists_via_existing_conversation(workspace):
    # The media chat must reuse the existing Conversation/Message store (no second chat system).
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    first = client.post(f"/workspaces/{ws}/media-ai/chat", headers=headers,
                        json={"content": "first question about transcript", "document_id": doc}).json()
    conv_id = first["conversation_id"]
    # continue the same conversation
    second = client.post(f"/workspaces/{ws}/media-ai/chat", headers=headers,
                         json={"content": "follow up on segment", "conversation_id": conv_id}).json()
    assert second["conversation_id"] == conv_id
    # the conversation is visible through the EXISTING chat API
    conv = client.get(f"/workspaces/{ws}/conversations/{conv_id}", headers=headers)
    assert conv.status_code == 200
    msgs = client.get(f"/workspaces/{ws}/conversations/{conv_id}/messages", headers=headers)
    assert msgs.status_code == 200
    assert msgs.json()["total"] == 4                       # 2 user + 2 assistant turns


def test_media_chat_ungrounded_when_no_media(workspace):
    client, headers, _uid, ws = workspace  # no media uploaded
    r = client.post(f"/workspaces/{ws}/media-ai/chat", headers=headers,
                    json={"content": "what happened?"})
    assert r.status_code == 200
    body = r.json()
    assert body["grounded"] is False
    assert body["citations"] == []


# --------------------------------------------------------------------- knowledge-asset actions
def test_ai_action_generates_summary_reusing_service(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/media-ai/action", headers=headers,
                    json={"action": "summary", "document_id": doc})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_type"] == "summary" and body["asset_id"]
    # the asset exists through the EXISTING summaries API
    got = client.get(f"/workspaces/{ws}/summaries/{body['asset_id']}", headers=headers)
    assert got.status_code == 200


def test_ai_action_maps_derived_actions_to_valid_types(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    for action, asset in [("study_guide", "note"), ("action_items", "note"),
                          ("minutes", "summary"), ("flashcards", "deck")]:
        r = client.post(f"/workspaces/{ws}/media-ai/action", headers=headers,
                        json={"action": action, "document_id": doc, "count": 5})
        assert r.status_code == 200, (action, r.text)
        assert r.json()["asset_type"] == asset


def test_ai_action_unknown_rejected(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    r = client.post(f"/workspaces/{ws}/media-ai/action", headers=headers,
                    json={"action": "teleport", "document_id": doc})
    assert r.status_code == 422


# --------------------------------------------------------------------- unified search
def test_unified_search_returns_temporal_and_documents(workspace):
    client, headers, _uid, ws = workspace
    _upload_media(client, headers, ws)
    r = client.get(f"/workspaces/{ws}/media-ai/search?q=transcript", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "temporal" in body and "documents" in body
    assert body["total"] == len(body["temporal"]) + len(body["documents"])
    assert any(res.get("start_ms") is not None for res in body["temporal"])


# --------------------------------------------------------------------- observability (Step 15)
def test_interaction_recording_and_observability(workspace):
    client, headers, _uid, ws = workspace
    doc = _upload_media(client, headers, ws)
    for ev in [{"event_type": "playback", "document_id": doc, "position_ms": 12000},
               {"event_type": "citation_click", "document_id": doc, "target": "cit1"},
               {"event_type": "timeline_click", "document_id": doc, "position_ms": 30000}]:
        rec = client.post(f"/workspaces/{ws}/media-ai/interactions", headers=headers, json=ev)
        assert rec.status_code == 201
    # a chat also records a media_chat interaction
    client.post(f"/workspaces/{ws}/media-ai/chat", headers=headers,
                json={"content": "transcript?", "document_id": doc})
    obs = client.get(f"/workspaces/{ws}/media-ai/observability", headers=headers)
    assert obs.status_code == 200
    body = obs.json()
    assert body["usage"]["playback"] == 1
    assert body["usage"]["citation_click"] == 1
    assert body["usage"].get("media_chat", 0) >= 1
    assert body["total"] >= 4
    assert len(body["recent"]) >= 4


def test_media_ai_requires_auth(workspace):
    client, _headers, _uid, ws = workspace
    assert client.get(f"/workspaces/{ws}/media-ai/overview").status_code in (401, 403)
