// Citation Intelligence API (Phase 3, Module 8). Read-only intelligence over a derived index of
// every citation across chat/summaries/notes/flashcards. The index refreshes transparently on the
// server; the client just queries. All routes are workspace-scoped and require the bearer token.

import { apiRequest } from "./client";
import type {
  CitationDetail,
  CitationExplanation,
  CitationListResponse,
  CitationSearchParams,
  CitationStats,
  RelatedKnowledge,
} from "../types";

const base = (ws: string) => `/workspaces/${ws}/citations`;

function toQuery(p: CitationSearchParams): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => { if (v !== undefined && v !== "") q.set(k, String(v)); });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function searchCitations(ws: string, params: CitationSearchParams = {}, signal?: AbortSignal) {
  return apiRequest<CitationListResponse>(`${base(ws)}${toQuery(params)}`, { signal });
}

export function getCitation(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<CitationDetail>(`${base(ws)}/${id}`, { signal });
}

// Resolve a citation from a chunk/document id — used when opening the panel from an AI answer.
export function citationByChunk(ws: string, opts: { chunk_id?: string; document_id?: string }, signal?: AbortSignal) {
  const q = new URLSearchParams();
  if (opts.chunk_id) q.set("chunk_id", opts.chunk_id);
  if (opts.document_id) q.set("document_id", opts.document_id);
  return apiRequest<CitationDetail>(`${base(ws)}/by-chunk?${q.toString()}`, { signal });
}

export function relatedKnowledge(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<RelatedKnowledge>(`${base(ws)}/${id}/related`, { signal });
}

export function explainCitation(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<CitationExplanation>(`${base(ws)}/${id}/explain`, { signal });
}

export function citationStats(ws: string, signal?: AbortSignal) {
  return apiRequest<CitationStats>(`${base(ws)}/stats`, { signal });
}

export function reindexCitations(ws: string) {
  return apiRequest<{ ok: boolean; citations: number }>(`${base(ws)}/reindex`, { method: "POST" });
}
