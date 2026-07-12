// Audio & Video AI Workspace API (Phase 5, Module 4) — the product-integration layer. Coordinates
// media processing + temporal intelligence + temporal retrieval + the answer service into one media
// experience: overview, library, unified timeline, playback meta, media AI chat (timestamp-cited),
// knowledge-asset actions, unified search, and interaction telemetry. Types self-contained.

import { API_BASE, apiRequest, getToken } from "./client";

const b = (ws: string) => `/workspaces/${ws}/media-ai`;

// ---- types -------------------------------------------------------------------------------
export interface Overview {
  workspace_id: string; recordings: number; audio: number; video: number; total_duration_ms: number;
  transcript_segments: number; speakers: number; chapters: number; topics: number; events: number;
  scenes: number; frames: number; temporal_searches: number; media_chats: number;
  interactions: Record<string, number>;
}
export interface LibraryItem {
  document_id: string; display_name: string; media_kind: string; duration_ms: number;
  processing_status: string; intelligence_ready: boolean; speaker_count: number; chapter_count: number;
  created_at: string | null;
}
export interface TimelineItem {
  kind: string; id: string; title: string; start_ms: number; end_ms: number; timespan: string;
  lane: string; metadata: Record<string, unknown>;
}
export interface Timeline { document_id: string; duration_ms: number; items: TimelineItem[]; lanes: string[]; }
export interface PlaybackMeta {
  document_id: string; media_kind: string; duration_ms: number; media_url: string;
  chapters: number; speakers: number; scenes: number; processing_status: string;
}
export interface MediaCitation {
  index: number | null; document_id: string | null; modality: string | null; start_ms: number;
  end_ms: number; timespan: string; speaker_label: string; scene_id: string | null;
  frame_id: string | null; text: string;
}
export interface MediaChatResponse {
  ok: boolean; conversation_id: string; document_id: string | null; answer: string; grounded: boolean;
  citations: MediaCitation[]; primary: string | null; retrieval_ms: number; latency_ms: number;
  context_size: number; user_message_id: string | null; assistant_message_id: string | null;
}
export interface AiActionResponse { action: string; asset_type: string; asset_id: string; status: string; route: string; }
export interface MediaSearchResponse {
  query: string; total: number; temporal: Record<string, unknown>[]; documents: Record<string, unknown>[]; total_ms: number;
}

// ---- calls --------------------------------------------------------------------------------
export const getOverview = (ws: string, s?: AbortSignal) => apiRequest<Overview>(`${b(ws)}/overview`, { signal: s });
export const getLibrary = (ws: string, s?: AbortSignal) => apiRequest<{ items: LibraryItem[]; total: number }>(`${b(ws)}/library`, { signal: s });
export const getTimeline = (ws: string, doc: string, s?: AbortSignal) => apiRequest<Timeline>(`${b(ws)}/${doc}/timeline`, { signal: s });
export const getPlayback = (ws: string, doc: string, s?: AbortSignal) => apiRequest<PlaybackMeta>(`${b(ws)}/${doc}/playback`, { signal: s });

export function mediaChat(ws: string, body: { content: string; conversation_id?: string; document_id?: string; top_k?: number }, s?: AbortSignal) {
  return apiRequest<MediaChatResponse>(`${b(ws)}/chat`, { method: "POST", body, signal: s });
}
export function runAction(ws: string, body: { action: string; document_id: string; focus?: string; count?: number }) {
  return apiRequest<AiActionResponse>(`${b(ws)}/action`, { method: "POST", body });
}
export function unifiedSearch(ws: string, q: string, documentId?: string, s?: AbortSignal) {
  const qs = new URLSearchParams({ q, ...(documentId ? { document_id: documentId } : {}) });
  return apiRequest<MediaSearchResponse>(`${b(ws)}/search?${qs}`, { signal: s });
}
export function recordInteraction(ws: string, body: { event_type: string; document_id?: string; target?: string; position_ms?: number; meta?: Record<string, unknown> }) {
  // fire-and-forget telemetry
  return apiRequest(`${b(ws)}/interactions`, { method: "POST", body }).catch(() => undefined);
}

// Fetch an authed media file as an object URL (HTML5 <video>/<audio> can't send a bearer header).
export async function fetchMediaUrl(ws: string, doc: string): Promise<string> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/workspaces/${ws}/documents/${doc}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new Error(`Failed to load media (${res.status})`);
  return URL.createObjectURL(await res.blob());
}

export function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

export const LANE_META: Record<string, { icon: string; color: string; label: string }> = {
  chapters: { icon: "📑", color: "#0ea5e9", label: "Chapters" },
  topics: { icon: "🏷", color: "#f59e0b", label: "Topics" },
  events: { icon: "⚡", color: "#a855f7", label: "Events" },
  speakers: { icon: "🎙", color: "#10b981", label: "Speakers" },
  scenes: { icon: "🎬", color: "#8b5cf6", label: "Scenes" },
};

export const AI_ACTIONS: { action: string; label: string; icon: string }[] = [
  { action: "summary", label: "Summary", icon: "📄" },
  { action: "notes", label: "Study Notes", icon: "📝" },
  { action: "flashcards", label: "Flashcards", icon: "🎴" },
  { action: "study_guide", label: "Study Guide", icon: "📚" },
  { action: "minutes", label: "Minutes", icon: "🗒" },
  { action: "action_items", label: "Action Items", icon: "✅" },
];
