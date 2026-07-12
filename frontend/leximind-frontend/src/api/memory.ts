// API client for the Phase-7 Module-2 Semantic Memory & Graph Retrieval. Workspace-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/memory`;

// ---------------------------------------------------------------- types
export interface RecognizedEntity {
  id: string;
  canonical_name: string;
  entity_type: string;
  aliases: string[];
  degree: number;
  mention_count: number;
}
export interface GraphHitOut {
  kind: string;
  key: string;
  text: string;
  entity_id: string | null;
  rel_id: string | null;
  canonical_name: string | null;
  entity_type: string | null;
  rel_type: string | null;
  source_name: string | null;
  target_name: string | null;
  hop_distance: number;
  score: number;
  signals: Record<string, number>;
}
export interface FusedHit {
  key: string;
  modality: string;
  fusion_score: number;
  content: string;
  contributing_modalities: string[];
}
export interface RetrieveResult {
  query: string;
  mode: string;
  recognized_entities: { id: string; name: string; type: string }[];
  seed_count: number;
  neighborhood: { nodes: number; edges: number; truncated: boolean; max_hop: number };
  hits: GraphHitOut[];
  context_text: string;
  citations: Record<string, unknown>[];
  fused: FusedHit[];
  cache_hit: boolean;
  avg_confidence: number;
  timings: Record<string, number>;
}
export interface NeighborhoodOut {
  seed: { id: string; name: string };
  nodes: { id: string; name: string; type: string; hop: number; degree: number }[];
  edges: { id: string; source: string; target: string; type: string; weight: number }[];
  truncated: boolean;
}
export interface MemoryLog {
  id: string;
  query: string;
  mode: string;
  seed_count: number;
  traversal_depth: number;
  traversal_strategy: string;
  neighborhood_size: number;
  edges_traversed: number;
  hits_returned: number;
  graph_hits: number;
  vector_hits: number;
  cache_hit: boolean;
  avg_confidence: number;
  total_ms: number;
  created_at: string;
}

// ---------------------------------------------------------------- calls
export const retrieveMemory = (
  ws: string,
  body: { query: string; hops?: number; strategy?: string; limit?: number; hybrid?: boolean; rel_types?: string[] },
  s?: AbortSignal,
) => apiRequest<RetrieveResult>(`${b(ws)}/retrieve`, { method: "POST", body, signal: s });

export const recognizeEntities = (ws: string, query: string, s?: AbortSignal) =>
  apiRequest<RecognizedEntity[]>(`${b(ws)}/recognize`, { method: "POST", body: { query }, signal: s });

export const getNeighborhood = (ws: string, entityId: string, hops = 1, s?: AbortSignal) =>
  apiRequest<NeighborhoodOut>(`${b(ws)}/entities/${entityId}/neighborhood?hops=${hops}`, { signal: s });

export const syncMemory = (ws: string) => apiRequest<Record<string, unknown>>(`${b(ws)}/sync`, { method: "POST", body: {} });
export const memoryStats = (ws: string, s?: AbortSignal) => apiRequest<Record<string, unknown>>(`${b(ws)}/stats`, { signal: s });
export const listMemoryLogs = (ws: string, s?: AbortSignal) => apiRequest<MemoryLog[]>(`${b(ws)}/logs`, { signal: s });

// ---------------------------------------------------------------- presentation
export const HIT_KIND_COLOR: Record<string, string> = {
  entity: "#6366f1", neighbor: "#0ea5e9", relationship: "#10b981", evidence: "#f59e0b",
  topic: "#8b5cf6", concept: "#ec4899", backlink: "#f43f5e", reference: "#14b8a6",
};
export const hitColor = (k: string) => HIT_KIND_COLOR[k] || "#94a3b8";
