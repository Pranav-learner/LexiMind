// Temporal Retrieval & Context API (Phase 5, Module 3). Retrieves time/speaker/topic/chapter/event/
// scene/frame/timestamp signals over processed media, then returns timeline-aware results + a
// timestamp-preserving prompt + temporal citations. Inspectable service (no live LLM). Types declared
// here (self-contained). All routes workspace-scoped, bearer-authenticated.

import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/temporal`;

// ---- types -------------------------------------------------------------------------------
export interface TemporalResult {
  key: string;
  modality: string;
  source_type: string;
  document_id: string | null;
  title: string;
  content: string;
  start_ms: number;
  end_ms: number;
  timespan: string;
  speaker_id: string | null;
  speaker_label: string;
  scene_id: string | null;
  chapter_id: string | null;
  frame_id: string | null;
  confidence: number;
  final_rank: number;
  metadata: Record<string, unknown>;
  explanation?: Record<string, unknown> | null;
}

export interface TemporalCitation {
  index: number;
  document_id: string | null;
  modality: string;
  start_ms: number;
  end_ms: number;
  timespan: string;
  speaker_label: string;
  scene_id: string | null;
  frame_id: string | null;
  text: string;
}

export interface RetrieverStat { modality: string; count: number; latency_ms: number; }
export interface ContextBlock {
  citation_index: number; modality: string; document_id: string; start_ms: number; end_ms: number;
  timespan: string | null; speaker_label: string; tokens: number; content: string;
}

export interface TemporalSearchResponse {
  query: string;
  intents: string[];
  detected: string[];
  primary: string;
  weights: Record<string, number>;
  time_filter: { start_ms: number; end_ms: number; anchor_ms: number } | null;
  total: number;
  total_ms: number;
  analysis_ms: number;
  fusion_ms: number;
  rerank_ms: number;
  context_ms: number;
  prompt_ms: number;
  retriever_stats: RetrieverStat[];
  results: TemporalResult[];
  citations: TemporalCitation[];
  prompt: string | null;
  context_blocks: ContextBlock[] | null;
}

export interface PromptPreview {
  query: string; query_type: string; prompt: string; system_prompt: string;
  citations: TemporalCitation[]; token_estimate: number;
}

export interface TemporalHealth { status: string; retrievers: string[]; indexed: Record<string, number>; }

export interface SearchBody {
  query: string;
  modalities?: string[];
  document_id?: string;
  top_k?: number;
  fusion?: string;
  rerank?: boolean;
  build_context?: boolean;
  explain?: boolean;
}

// ---- calls --------------------------------------------------------------------------------
export function temporalSearch(ws: string, body: SearchBody, signal?: AbortSignal) {
  return apiRequest<TemporalSearchResponse>(`${b(ws)}/search`, { method: "POST", body, signal });
}

export function promptPreview(ws: string, body: SearchBody, signal?: AbortSignal) {
  return apiRequest<PromptPreview>(`${b(ws)}/prompt`, { method: "POST", body, signal });
}

export function temporalHealth(ws: string, signal?: AbortSignal) {
  return apiRequest<TemporalHealth>(`${b(ws)}/health`, { signal });
}

// ---- helpers ------------------------------------------------------------------------------
export function fmtTime(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = String(m).padStart(2, "0"), ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

export const MODALITY_META: Record<string, { icon: string; color: string; label: string }> = {
  transcript: { icon: "💬", color: "#6366f1", label: "Transcript" },
  speaker: { icon: "🎙", color: "#10b981", label: "Speaker" },
  chapter: { icon: "📑", color: "#0ea5e9", label: "Chapter" },
  topic: { icon: "🏷", color: "#f59e0b", label: "Topic" },
  event: { icon: "⚡", color: "#a855f7", label: "Event" },
  scene: { icon: "🎬", color: "#8b5cf6", label: "Scene" },
  frame: { icon: "🖼", color: "#14b8a6", label: "On-screen" },
  subtitle: { icon: "📝", color: "#0ea5e9", label: "Subtitle" },
  timestamp: { icon: "⏱", color: "#ef4444", label: "Timestamp" },
};
