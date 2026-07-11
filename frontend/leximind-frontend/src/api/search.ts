// Multimodal Search API (Phase 4, Module 3). Unified search across text/OCR/image/diagram/table/
// metadata with fusion + cross-modal reranking. All routes are workspace-scoped and require the token.

import { apiRequest } from "./client";
import type { SearchModality, SearchResponse, SearchStats } from "../types";

const b = (ws: string) => `/workspaces/${ws}`;

export interface SearchBody {
  query: string;
  modalities?: SearchModality[];
  document_id?: string;
  top_k?: number;
  fusion?: "rrf" | "weighted_sum";
  normalize?: "minmax" | "zscore";
  rerank?: boolean;
  explain?: boolean;
}

export function search(ws: string, body: SearchBody, signal?: AbortSignal) {
  return apiRequest<SearchResponse>(`${b(ws)}/search`, { method: "POST", body, signal });
}

export function searchByModality(ws: string, modality: SearchModality, q: string, signal?: AbortSignal) {
  return apiRequest<SearchResponse>(`${b(ws)}/search/modality/${modality}?q=${encodeURIComponent(q)}`, { signal });
}

export function getSuggestions(ws: string, q: string, signal?: AbortSignal) {
  return apiRequest<{ query: string; suggestions: string[] }>(`${b(ws)}/search/suggestions?q=${encodeURIComponent(q)}`, { signal });
}

export function getStats(ws: string, signal?: AbortSignal) {
  return apiRequest<SearchStats>(`${b(ws)}/search/stats`, { signal });
}

export function getHealth(ws: string, signal?: AbortSignal) {
  return apiRequest<{ status: string; retrievers: string[]; text_backend: string; indexed: Record<string, number>; embedding_queue: Record<string, number> }>(`${b(ws)}/search/health`, { signal });
}
