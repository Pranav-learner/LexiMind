// Audio & Video Processing API (Phase 5, Module 1). Processing is asynchronous: `uploadMedia`
// returns a queued/processing job; poll `getMediaStatus` until a terminal state. All routes are
// workspace-scoped and require the bearer token. Types are declared here (self-contained) so this
// module can ship without touching the shared types barrel.

import { API_BASE, apiRequest, getToken } from "./client";

const b = (ws: string) => `/workspaces/${ws}/media`;

export const TERMINAL: string[] = ["completed", "failed", "cancelled"];
export function isTerminal(status: string): boolean {
  return TERMINAL.includes(status);
}

// ---- types -------------------------------------------------------------------------------
export interface MediaJob {
  id: string;
  workspace_id: string;
  document_id: string;
  status: string;
  stage: string;
  progress: number;
  error: string | null;
  attempts: number;
  media_kind: string;
  media_category: string;
  category_confidence: number | null;
  language: string;
  duration_ms: number;
  width: number;
  height: number;
  fps: number | null;
  sample_rate: number;
  channels: number;
  video_codec: string;
  audio_codec: string;
  container: string;
  bitrate: number;
  speaker_count: number;
  scene_count: number;
  frame_count: number;
  subtitle_count: number;
  segment_count: number;
  ocr_frame_count: number;
  chunk_count: number;
  transcript_chars: number;
  word_count: number;
  avg_speech_rate: number | null;
  transcription_confidence: number | null;
  processing_ms: number;
  pipeline_version: string;
  created_at: string;
  updated_at: string;
}

export interface MediaLog { stage: string; level: string; message: string; created_at: string; }
export interface MediaJobDetail extends MediaJob { logs: MediaLog[]; }
export interface UploadResponse { document_id: string; filename: string; media_kind: string; job: MediaJob; }

export interface TranscriptSegment {
  id: string; segment_index: number; start_ms: number; end_ms: number; text: string;
  speaker_id: string | null; speaker_label: string; confidence: number | null; language: string;
}
export interface TranscriptResponse {
  document_id: string; language: string; segment_count: number; duration_ms: number;
  segments: TranscriptSegment[];
}
export interface Speaker {
  id: string; speaker_label: string; display_name: string | null; total_speaking_ms: number;
  turn_count: number; segment_count: number; confidence: number | null;
}
export interface SpeakerTurn { speaker_id: string | null; speaker_label: string; turn_index: number; start_ms: number; end_ms: number; }
export interface SpeakerTimeline { document_id: string; speaker_count: number; speakers: Speaker[]; timeline: SpeakerTurn[]; }
export interface MediaFrame {
  id: string; frame_index: number; timestamp_ms: number; scene_id: string | null; scene_index: number | null;
  width: number; height: number; hash: string; is_keyframe: boolean; extraction: string;
  ocr_text: string | null; ocr_confidence: number | null;
}
export interface Scene { id: string; scene_index: number; start_ms: number; end_ms: number; duration_ms: number; score: number | null; representative_frame_id: string | null; }
export interface Subtitle { id: string; subtitle_index: number; start_ms: number; end_ms: number; text: string; source: string; language: string; }
export interface MediaChunk {
  id: string; chunk_type: string; source: string; chunk_index: number; start_ms: number; end_ms: number;
  speaker_id: string | null; scene_id: string | null; asset_id: string | null; content: string;
  meta: Record<string, unknown> | null; embedding_status: string;
}
export interface MediaMetadata {
  media_kind: string; media_category: string; language: string; duration_ms: number;
  duration_readable: string; video: { width: number; height: number; fps: number | null; codec: string } | null;
  audio: { sample_rate: number; channels: number; codec: string }; container: string; bitrate: number;
  speaker_count: number; scene_count: number; frame_count: number; subtitle_count: number;
  segment_count: number; ocr_frame_count: number; chunk_count: number; transcript_length: number;
  word_count: number; avg_speech_rate: number | null; transcription_confidence: number | null;
  processing_ms: number; stage_latencies: Record<string, number>; cache_hits: number; pipeline_version: string;
}

// ---- reads --------------------------------------------------------------------------------
export function getMediaStatus(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<MediaJob | null>(`${b(ws)}/${docId}/status`, { signal });
}
export function getTranscript(ws: string, docId: string, speakerId?: string, signal?: AbortSignal) {
  const q = speakerId ? `?speaker_id=${speakerId}` : "";
  return apiRequest<TranscriptResponse>(`${b(ws)}/${docId}/transcript${q}`, { signal });
}
export function getSpeakers(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<SpeakerTimeline>(`${b(ws)}/${docId}/speakers`, { signal });
}
export function getFrames(ws: string, docId: string, sceneId?: string, signal?: AbortSignal) {
  const q = sceneId ? `?scene_id=${sceneId}` : "";
  return apiRequest<MediaFrame[]>(`${b(ws)}/${docId}/frames${q}`, { signal });
}
export function frameThumbnailUrl(ws: string, docId: string, frameId: string) {
  return `${API_BASE}${b(ws)}/${docId}/frames/${frameId}/thumbnail`;
}
export function getScenes(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<Scene[]>(`${b(ws)}/${docId}/scenes`, { signal });
}
export function getSubtitles(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<Subtitle[]>(`${b(ws)}/${docId}/subtitles`, { signal });
}
export function getMediaChunks(ws: string, docId: string, chunkType?: string, signal?: AbortSignal) {
  const q = chunkType ? `?chunk_type=${chunkType}` : "";
  return apiRequest<MediaChunk[]>(`${b(ws)}/${docId}/chunks${q}`, { signal });
}
export function getMetadata(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<MediaMetadata>(`${b(ws)}/${docId}/metadata`, { signal });
}
export function getJobDetail(ws: string, jobId: string, signal?: AbortSignal) {
  return apiRequest<MediaJobDetail>(`${b(ws)}/jobs/${jobId}`, { signal });
}

// ---- commands -----------------------------------------------------------------------------
export function reprocess(ws: string, docId: string, force = true) {
  return apiRequest<MediaJob>(`${b(ws)}/${docId}/process`, { method: "POST", body: { force } });
}
export function retryJob(ws: string, jobId: string) {
  return apiRequest<MediaJob>(`${b(ws)}/jobs/${jobId}/retry`, { method: "POST" });
}
export function cancelJob(ws: string, jobId: string) {
  return apiRequest<MediaJob>(`${b(ws)}/jobs/${jobId}/cancel`, { method: "POST" });
}

// Upload a single media file (XHR so we can report upload progress; fetch can't).
export function uploadMedia(ws: string, file: File, onProgress?: (pct: number) => void): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/workspaces/${ws}/media`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    if (onProgress) {
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100)); };
    }
    xhr.onload = () => {
      let data: unknown = null;
      try { data = xhr.responseText ? JSON.parse(xhr.responseText) : null; } catch { data = null; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as UploadResponse);
      else {
        const detail = data && typeof data === "object" && "detail" in data
          ? String((data as { detail: unknown }).detail) : `Upload failed (${xhr.status})`;
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload."));
    xhr.onabort = () => reject(new Error("Upload aborted."));
    xhr.send(form);
  });
}

// Poll a media job until terminal.
export async function pollMedia(
  ws: string, docId: string,
  { onUpdate, signal, intervalMs = 1200 }: { onUpdate?: (j: MediaJob) => void; signal?: AbortSignal; intervalMs?: number } = {},
): Promise<MediaJob | null> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const j = await getMediaStatus(ws, docId, signal);
    if (!j) return null;
    onUpdate?.(j);
    if (isTerminal(j.status)) return j;
    await wait(intervalMs, signal);
  }
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => { clearTimeout(t); signal?.removeEventListener("abort", onAbort); reject(new DOMException("Aborted", "AbortError")); };
    const t = setTimeout(() => { signal?.removeEventListener("abort", onAbort); resolve(); }, ms);
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
  });
}

// ---- small formatting helpers (shared by media UI) ---------------------------------------
export function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}
