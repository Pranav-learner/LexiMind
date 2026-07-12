// API client for the Phase-7 Module-1 Knowledge Graph (entity/relationship inspection + build). Ws-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/graph`;

// ---------------------------------------------------------------- types
export interface GraphEntity {
  id: string;
  entity_type: string;
  canonical_name: string;
  normalized_name: string;
  aliases: string[];
  description: string | null;
  confidence: number;
  mention_count: number;
  degree: number;
  source_refs: Record<string, unknown>[];
  status: string;
  version: number;
}
export interface GraphRelationship {
  id: string;
  rel_type: string;
  directed: boolean;
  weight: number;
  confidence: number;
  mention_count: number;
  source_id: string;
  target_id: string;
  source_name: string | null;
  target_name: string | null;
  evidence: Record<string, unknown>[];
  version: number;
}
export interface EntityDetail extends GraphEntity {
  relationships: GraphRelationship[];
}
export interface GraphLog {
  id: string;
  document_id: string | null;
  scope: string;
  status: string;
  pipeline_version: string;
  sources_processed: number;
  chunks_processed: number;
  entities_extracted: number;
  entities_created: number;
  entities_merged: number;
  relationships_extracted: number;
  relationships_created: number;
  duplicates_merged: number;
  validation_errors: number;
  validation_warnings: number;
  avg_confidence: number;
  processing_ms: number;
  error: string | null;
  created_at: string;
}
export interface GraphLogDetail extends GraphLog {
  report: { validation?: Record<string, unknown>; events?: Record<string, number> } | null;
}
export interface GraphStats {
  entities: number;
  relationships: number;
  merged_entities: number;
  entity_types: Record<string, number>;
  relationship_types: Record<string, number>;
  density: number;
}
export interface ValidationReport {
  ok: boolean;
  errors: { kind: string; detail: string; ref: string }[];
  warnings: { kind: string; detail: string; ref: string }[];
  error_count: number;
  warning_count: number;
  counts: Record<string, number>;
}

// ---------------------------------------------------------------- calls
export const buildWorkspaceGraph = (ws: string) =>
  apiRequest<GraphLog>(`${b(ws)}/build`, { method: "POST", body: {} });
export const extractText = (ws: string, text: string, source_type = "text") =>
  apiRequest<GraphLogDetail>(`${b(ws)}/extract`, { method: "POST", body: { text, source_type } });
export const searchEntities = (ws: string, opts: { query?: string; type?: string; limit?: number } = {}, s?: AbortSignal) => {
  const q = new URLSearchParams();
  if (opts.query) q.set("query", opts.query);
  if (opts.type) q.set("type", opts.type);
  if (opts.limit) q.set("limit", String(opts.limit));
  return apiRequest<GraphEntity[]>(`${b(ws)}/entities?${q.toString()}`, { signal: s });
};
export const getEntity = (ws: string, id: string, s?: AbortSignal) =>
  apiRequest<EntityDetail>(`${b(ws)}/entities/${id}`, { signal: s });
export const searchRelationships = (ws: string, type?: string, s?: AbortSignal) =>
  apiRequest<GraphRelationship[]>(`${b(ws)}/relationships${type ? `?type=${type}` : ""}`, { signal: s });
export const graphStats = (ws: string, s?: AbortSignal) => apiRequest<GraphStats>(`${b(ws)}/stats`, { signal: s });
export const validateGraph = (ws: string, s?: AbortSignal) => apiRequest<ValidationReport>(`${b(ws)}/validate`, { signal: s });
export const listGraphLogs = (ws: string, s?: AbortSignal) => apiRequest<GraphLog[]>(`${b(ws)}/logs`, { signal: s });

// ---------------------------------------------------------------- presentation
export const ENTITY_TYPE_COLOR: Record<string, string> = {
  person: "#8b5cf6", organization: "#0ea5e9", location: "#14b8a6", technology: "#6366f1",
  language: "#f59e0b", framework: "#10b981", algorithm: "#ec4899", data_structure: "#f43f5e",
  library: "#22c55e", paper: "#64748b", book: "#a16207", product: "#3b82f6", concept: "#94a3b8",
  custom: "#cbd5e1",
};
export const entityColor = (t: string) => ENTITY_TYPE_COLOR[t] || "#94a3b8";
