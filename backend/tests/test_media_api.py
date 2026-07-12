"""Integration tests for the media (audio/video) HTTP API.

Drives the full lifecycle over HTTP with the in-memory DB + InlineRunner + FakeMediaEngine (wired in
conftest): upload → synchronous processing → transcript / speakers / frames / scenes / subtitles /
OCR / chunks / metadata, plus retry & cancel state transitions. No ffmpeg/whisper involved.
"""

from __future__ import annotations


def _upload(client, headers, ws, *, name="CS101 Lecture.mp4", content=b"\x00\x00\x00fakevideo"):
    return client.post(f"/workspaces/{ws}/media", headers=headers,
                       files=[("file", (name, content, "video/mp4"))])


# --------------------------------------------------------------------- upload + process
def test_upload_processes_media_end_to_end(workspace):
    client, headers, _uid, ws = workspace
    resp = _upload(client, headers, ws)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    doc_id = body["document_id"]
    assert body["media_kind"] == "video"
    job = body["job"]
    # InlineRunner ran the FakeMediaEngine synchronously → job is completed with temporal outputs.
    assert job["status"] == "completed"
    assert job["media_category"] == "lecture"          # from filename keyword
    assert job["segment_count"] == 4
    assert job["speaker_count"] == 2
    assert job["scene_count"] == 2
    assert job["frame_count"] == 2
    assert job["subtitle_count"] == 2
    assert job["chunk_count"] > 0
    assert job["duration_ms"] == 60_000
    assert job["word_count"] > 0

    # document-level status endpoint reflects the same job
    st = client.get(f"/workspaces/{ws}/media/{doc_id}/status", headers=headers)
    assert st.status_code == 200
    assert st.json()["status"] == "completed"


def test_uploaded_media_appears_as_media_document(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    doc = client.get(f"/workspaces/{ws}/documents/{doc_id}", headers=headers)
    assert doc.status_code == 200
    assert doc.json()["media_type"] == "video"


# --------------------------------------------------------------------- outputs
def test_transcript_endpoint(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    r = client.get(f"/workspaces/{ws}/media/{doc_id}/transcript", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["segment_count"] == 4
    assert len(body["segments"]) == 4
    assert body["segments"][0]["speaker_label"].startswith("SPEAKER_")
    # segments are time-ordered and carry a speaker id
    starts = [s["start_ms"] for s in body["segments"]]
    assert starts == sorted(starts)
    assert body["segments"][0]["speaker_id"]


def test_transcript_filtered_by_speaker(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    speakers = client.get(f"/workspaces/{ws}/media/{doc_id}/speakers", headers=headers).json()["speakers"]
    spk_id = speakers[0]["id"]
    r = client.get(f"/workspaces/{ws}/media/{doc_id}/transcript?speaker_id={spk_id}", headers=headers)
    assert r.status_code == 200
    assert all(s["speaker_id"] == spk_id for s in r.json()["segments"])


def test_speakers_timeline_endpoint(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    r = client.get(f"/workspaces/{ws}/media/{doc_id}/speakers", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["speaker_count"] == 2
    assert len(body["speakers"]) == 2
    assert len(body["timeline"]) == 4                 # one turn per segment
    tl = [t["start_ms"] for t in body["timeline"]]
    assert tl == sorted(tl)
    # each speaker profile carries its derived segment_count
    assert sum(s["segment_count"] for s in body["speakers"]) == 4


def test_scenes_and_frames_endpoints(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    scenes = client.get(f"/workspaces/{ws}/media/{doc_id}/scenes", headers=headers)
    assert scenes.status_code == 200
    sc = scenes.json()
    assert len(sc) == 2
    assert sc[0]["representative_frame_id"]           # resolved during finalization

    frames = client.get(f"/workspaces/{ws}/media/{doc_id}/frames", headers=headers)
    assert frames.status_code == 200
    fr = frames.json()
    assert len(fr) == 2
    assert fr[0]["scene_id"]                          # frame linked to its scene
    assert fr[0]["is_keyframe"] is True

    # scene-scoped frame filter
    scoped = client.get(f"/workspaces/{ws}/media/{doc_id}/frames?scene_id={sc[0]['id']}", headers=headers)
    assert scoped.status_code == 200
    assert all(f["scene_id"] == sc[0]["id"] for f in scoped.json())


def test_frame_thumbnail_served(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    frames = client.get(f"/workspaces/{ws}/media/{doc_id}/frames", headers=headers).json()
    fid = frames[0]["id"]
    thumb = client.get(f"/workspaces/{ws}/media/{doc_id}/frames/{fid}/thumbnail", headers=headers)
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/")


def test_subtitles_endpoint(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    r = client.get(f"/workspaces/{ws}/media/{doc_id}/subtitles", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert r.json()[0]["source"] == "embedded"


def test_ocr_endpoint_returns_on_screen_text(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    r = client.get(f"/workspaces/{ws}/media/{doc_id}/ocr", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ocr_frame_count"] >= 1
    assert all(f["ocr_text"] for f in body["frames"])


def test_chunks_endpoint_and_filter(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    allc = client.get(f"/workspaces/{ws}/media/{doc_id}/chunks", headers=headers)
    assert allc.status_code == 200
    types = {c["chunk_type"] for c in allc.json()}
    assert {"transcript", "speaker", "scene", "subtitle", "ocr"} <= types
    # every chunk sits in the future embedding queue
    assert all(c["embedding_status"] == "pending" for c in allc.json())
    # filtered
    only = client.get(f"/workspaces/{ws}/media/{doc_id}/chunks?chunk_type=transcript", headers=headers)
    assert only.status_code == 200
    assert all(c["chunk_type"] == "transcript" for c in only.json())
    assert all(c["end_ms"] >= c["start_ms"] for c in only.json())


def test_metadata_endpoint(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    r = client.get(f"/workspaces/{ws}/media/{doc_id}/metadata", headers=headers)
    assert r.status_code == 200
    md = r.json()
    assert md["media_kind"] == "video"
    assert md["video"]["width"] == 1280
    assert md["speaker_count"] == 2
    assert md["chunk_count"] > 0
    assert "stage_latencies" in md
    assert md["pipeline_version"].startswith("media-v")


# --------------------------------------------------------------------- validation errors
def test_upload_rejects_unsupported_type(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(f"/workspaces/{ws}/media", headers=headers,
                    files=[("file", ("notes.pdf", b"%PDF-1.4", "application/pdf"))])
    assert r.status_code == 415


def test_upload_rejects_empty_file(workspace):
    client, headers, _uid, ws = workspace
    r = client.post(f"/workspaces/{ws}/media", headers=headers,
                    files=[("file", ("empty.mp3", b"", "audio/mpeg"))])
    assert r.status_code == 422


# --------------------------------------------------------------------- job detail / retry / cancel
def test_job_detail_has_logs(workspace):
    client, headers, _uid, ws = workspace
    job = _upload(client, headers, ws).json()["job"]
    r = client.get(f"/workspaces/{ws}/media/jobs/{job['id']}", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["logs"]) >= 1


def test_retry_completed_job_conflicts(workspace):
    client, headers, _uid, ws = workspace
    job = _upload(client, headers, ws).json()["job"]
    r = client.post(f"/workspaces/{ws}/media/jobs/{job['id']}/retry", headers=headers)
    assert r.status_code == 409          # cannot retry a completed job


def test_cancel_queued_job(workspace):
    # Use a deferred (no-op) runner so the job stays queued and can be cancelled.
    from app.media.api import get_media_runner
    from app.media.runner import DeferredRunner
    client, headers, _uid, ws = workspace
    client.app.dependency_overrides[get_media_runner] = lambda: DeferredRunner()
    try:
        job = _upload(client, headers, ws).json()["job"]
        assert job["status"] == "queued"
        cancel = client.post(f"/workspaces/{ws}/media/jobs/{job['id']}/cancel", headers=headers)
        assert cancel.status_code == 200
        assert cancel.json()["status"] == "cancelled"
    finally:
        client.app.dependency_overrides.pop(get_media_runner, None)


def test_reprocess_force_reruns(workspace):
    client, headers, _uid, ws = workspace
    doc_id = _upload(client, headers, ws).json()["document_id"]
    r = client.post(f"/workspaces/{ws}/media/{doc_id}/process", headers=headers, json={"force": True})
    assert r.status_code == 202
    assert r.json()["status"] == "completed"


def test_media_scoped_to_owner_workspace(workspace):
    client, headers, _uid, ws = workspace
    # a bogus document id in a valid workspace → 404
    r = client.get(f"/workspaces/{ws}/media/doc_missing/transcript", headers=headers)
    assert r.status_code == 404
