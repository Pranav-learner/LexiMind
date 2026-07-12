// Audio & Video Studio (Phase 5, Module 1) — the media ingestion hub. Route:
//   /workspace/:workspaceId/media
//
// Upload a recording (audio: mp3/wav/m4a/flac/aac · video: mp4/mkv/mov/avi/webm) and the platform
// asynchronously transcribes it, diarizes speakers, detects scenes, extracts frames + on-screen OCR,
// and pulls embedded subtitles — turning raw media into timestamp-aware temporal knowledge. Left: the
// media library (recordings in this workspace). Right: a live processing dashboard for the selected
// recording, then its transcript / speakers / scenes / subtitles / chunks / metadata. This module is
// the ingestion layer only; retrieval/chat over media arrive in a later module.

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { listDocuments } from "../api/documents";
import {
  cancelJob,
  fmtTime,
  getMediaStatus,
  isTerminal,
  pollMedia,
  retryJob,
  uploadMedia,
  type MediaJob,
} from "../api/media";
import type { LibraryDocument } from "../types";
import MediaDetail from "../components/media/MediaDetail";
import MediaProgress from "../components/media/MediaProgress";
import "../styles/media.css";

const ACCEPT = ".mp3,.wav,.m4a,.flac,.aac,.mp4,.mkv,.mov,.avi,.webm";
const KIND_ICON: Record<string, string> = { audio: "🎧", video: "🎬" };

export default function MediaWorkspace() {
  const { workspaceId = "" } = useParams();
  const [media, setMedia] = useState<LibraryDocument[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [job, setJob] = useState<MediaJob | null>(null);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const pollAbort = useRef<AbortController | null>(null);

  const loadLibrary = useCallback(async () => {
    try {
      const res = await listDocuments(workspaceId, { page_size: 100 });
      const recordings = res.items.filter((d) => d.media_type === "audio" || d.media_type === "video");
      setMedia(recordings);
      setSelected((cur) => cur ?? (recordings[0]?.id ?? null));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load media library.");
    }
  }, [workspaceId]);

  useEffect(() => { loadLibrary(); }, [loadLibrary]);

  // Load + live-poll the selected recording's job.
  useEffect(() => {
    pollAbort.current?.abort();
    if (!selected) { setJob(null); return; }
    const ctrl = new AbortController();
    pollAbort.current = ctrl;
    setJob(null);
    (async () => {
      try {
        const initial = await getMediaStatus(workspaceId, selected, ctrl.signal);
        setJob(initial);
        if (initial && !isTerminal(initial.status)) {
          await pollMedia(workspaceId, selected, { onUpdate: setJob, signal: ctrl.signal });
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof ApiError ? err.message : "Failed to load processing status.");
      }
    })();
    return () => ctrl.abort();
  }, [workspaceId, selected]);

  const onFiles = async (files: FileList | null) => {
    if (!files || !files.length) return;
    setError(null);
    for (const file of Array.from(files)) {
      try {
        setUploadPct(0);
        const res = await uploadMedia(workspaceId, file, setUploadPct);
        setUploadPct(null);
        await loadLibrary();
        setSelected(res.document_id);
      } catch (err) {
        setUploadPct(null);
        setError(err instanceof Error ? err.message : "Upload failed.");
      }
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const doRetry = async () => {
    if (!job) return;
    try {
      const j = await retryJob(workspaceId, job.id);
      setJob(j);
      if (selected) await pollMedia(workspaceId, selected, { onUpdate: setJob });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Retry failed.");
    }
  };

  const doCancel = async () => {
    if (!job) return;
    try {
      setJob(await cancelJob(workspaceId, job.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Cancel failed.");
    }
  };

  return (
    <div className="media-page">
      <header className="media-header">
        <div>
          <Link to={`/workspace/${workspaceId}`} className="media-back">← Workspace</Link>
          <h1>🎬 Audio &amp; Video Studio</h1>
          <p className="media-sub">
            Upload lectures, meetings, podcasts &amp; tutorials — LexiMind turns them into
            timestamp-aware knowledge (transcript, speakers, scenes, on-screen text).
          </p>
        </div>
        <div className="media-upload">
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPT}
            multiple
            hidden
            onChange={(e) => onFiles(e.target.files)}
          />
          <button className="media-btn media-btn--primary" onClick={() => fileRef.current?.click()}>
            + Upload recording
          </button>
          {uploadPct !== null && (
            <div className="media-upload-bar">
              <div className="media-upload-fill" style={{ width: `${uploadPct}%` }} />
              <span>{uploadPct}%</span>
            </div>
          )}
        </div>
      </header>

      {error && <div className="media-banner media-banner--error">{error}</div>}

      <div className="media-body">
        <aside className="media-library">
          <h2>Recordings ({media.length})</h2>
          {!media.length && <p className="media-empty">No recordings yet. Upload one to begin.</p>}
          <ul>
            {media.map((d) => (
              <li key={d.id}>
                <button
                  className={`media-lib-item ${selected === d.id ? "is-active" : ""}`}
                  onClick={() => setSelected(d.id)}
                >
                  <span className="media-lib-icon">{KIND_ICON[d.media_type] || "🎞"}</span>
                  <span className="media-lib-name" title={d.display_name}>{d.display_name}</span>
                  <span className={`media-dot media-dot--${d.processing_status}`} />
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <main className="media-main">
          {!selected && <p className="media-empty">Select or upload a recording.</p>}
          {selected && job && (
            <>
              <div className="media-summary">
                <span className="media-summary-icon">{KIND_ICON[job.media_kind] || "🎞"}</span>
                <div>
                  <div className="media-summary-cat">
                    {job.media_category} · {job.media_kind}
                    {job.duration_ms > 0 && <> · {fmtTime(job.duration_ms)}</>}
                  </div>
                  <div className="media-summary-stats">
                    {job.segment_count} segments · {job.speaker_count} speakers · {job.scene_count} scenes ·{" "}
                    {job.frame_count} frames · {job.chunk_count} chunks
                  </div>
                </div>
              </div>
              <MediaProgress job={job} onRetry={doRetry} onCancel={doCancel} />
              {job.status === "completed" && <MediaDetail ws={workspaceId} docId={selected} />}
            </>
          )}
          {selected && !job && <p className="media-empty">No processing job for this recording yet.</p>}
        </main>
      </div>
    </div>
  );
}
