// Multimodal Context Engineering API (Phase 4, Module 4). Builds an optimized, cited, explainable
// multimodal prompt from Module-3 retrieval. All routes are workspace-scoped and require the token.

import { apiRequest } from "./client";
import type { ContextObservability, ContextResponse } from "../types";

const b = (ws: string) => `/workspaces/${ws}/context`;

export interface ContextBuildBody {
  query: string;
  modalities?: string[];
  document_id?: string;
  top_k?: number;
  token_budget?: number;
  compress?: boolean;
  dedup?: boolean;
  explain?: boolean;
  developer?: boolean;
}

export function buildContext(ws: string, body: ContextBuildBody, signal?: AbortSignal) {
  return apiRequest<ContextResponse>(`${b(ws)}/build`, { method: "POST", body, signal });
}

export function getObservability(ws: string, signal?: AbortSignal) {
  return apiRequest<ContextObservability>(`${b(ws)}/observability`, { signal });
}
