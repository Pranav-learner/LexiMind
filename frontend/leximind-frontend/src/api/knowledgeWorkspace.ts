// API client for the Phase-7 Module-4 Interactive Knowledge Workspace. Workspace-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/knowledge-workspace`;

// ---------------------------------------------------------------- types
export interface GraphNode { id: string; name: string; type: string; degree: number; hop?: number }
export interface GraphEdge { id: string; source: string; target: string; type: string; weight: number; status?: string }
export interface GraphView { seed: string | null; nodes: GraphNode[]; edges: GraphEdge[]; node_count: number; edge_count: number }
export interface Overview {
  workspace_id: string; entities: number; relationships: number; density: number;
  entity_types: Record<string, number>;
  top_concepts: { id: string; name: string; type: string; degree: number }[];
  activity: Record<string, number>;
}
export interface EntityDetail {
  id: string; entity_type: string; canonical_name: string; aliases: string[]; description: string | null;
  confidence: number; mention_count: number; degree: number; source_refs: Record<string, unknown>[];
  status: string; version: number;
  relationships: { id: string; rel_type: string; source_name: string | null; target_name: string | null; source_id: string; target_id: string; weight: number }[];
  reasoning: { dependencies?: unknown[]; root_causes?: { entity: string; depth: number }[] };
}
export interface RelationshipDetail {
  id: string; rel_type: string; directed: boolean; weight: number; confidence: number; status: string;
  version: number; inferred: boolean; evidence: Record<string, unknown>[];
  source: { id: string; name: string | null }; target: { id: string; name: string | null };
  why_connected: { chain: string; path_confidence: number }[];
}
export interface SearchResult {
  query: string; mode: string;
  entities: { id: string; name: string; type: string }[];
  hits: Record<string, unknown>[]; context_text: string; citations: Record<string, unknown>[];
  fused: Record<string, unknown>[];
}
export interface TimelineEvent { type: string; at: string | null; name?: string; entity_type?: string; rel_type?: string; scope?: string; status?: string }
export interface Analytics {
  entities: number; relationships: number; merged_entities: number; inferred_relationships: number;
  density: number; entity_types: Record<string, number>; relationship_types: Record<string, number>;
  top_connected: { id: string; name: string; type: string; degree: number }[];
  most_referenced: { id: string; name: string; mentions: number }[];
  growth: { builds: number; entities_created: number; agent_contributions: number };
  reasoning: Record<string, unknown>;
}
export interface GraphChatResponse { conversation_id: string; answer: string; citations: Record<string, unknown>[]; grounded: boolean }
export interface Activity { id: string; activity_type: string; target_id: string | null; detail: Record<string, unknown> | null; created_at: string | null }

// ---------------------------------------------------------------- calls
export const overview = (ws: string, s?: AbortSignal) => apiRequest<Overview>(`${b(ws)}/overview`, { signal: s });
export const graphView = (ws: string, opts: { seed?: string; hops?: number; limit?: number } = {}, s?: AbortSignal) => {
  const q = new URLSearchParams();
  if (opts.seed) q.set("seed", opts.seed);
  if (opts.hops) q.set("hops", String(opts.hops));
  if (opts.limit) q.set("limit", String(opts.limit));
  return apiRequest<GraphView>(`${b(ws)}/graph?${q.toString()}`, { signal: s });
};
export const entityDetail = (ws: string, id: string, s?: AbortSignal) => apiRequest<EntityDetail>(`${b(ws)}/entities/${id}`, { signal: s });
export const relationshipDetail = (ws: string, id: string, s?: AbortSignal) => apiRequest<RelationshipDetail>(`${b(ws)}/relationships/${id}`, { signal: s });
export const knowledgeSearch = (ws: string, query: string, hybrid = false, s?: AbortSignal) =>
  apiRequest<SearchResult>(`${b(ws)}/search`, { method: "POST", body: { query, hybrid }, signal: s });
export const timeline = (ws: string, s?: AbortSignal) => apiRequest<TimelineEvent[]>(`${b(ws)}/timeline`, { signal: s });
export const analytics = (ws: string, s?: AbortSignal) => apiRequest<Analytics>(`${b(ws)}/analytics`, { signal: s });
export const activity = (ws: string, s?: AbortSignal) => apiRequest<Activity[]>(`${b(ws)}/activity`, { signal: s });
export const graphChat = (ws: string, content: string, conversation_id?: string, s?: AbortSignal) =>
  apiRequest<GraphChatResponse>(`${b(ws)}/chat`, { method: "POST", body: { content, conversation_id }, signal: s });
export const editGraph = (ws: string, op: string, params: Record<string, unknown>) =>
  apiRequest<Record<string, unknown>>(`${b(ws)}/edit`, { method: "POST", body: { op, params } });

// ---------------------------------------------------------------- presentation
export const ENTITY_COLOR: Record<string, string> = {
  person: "#8b5cf6", organization: "#0ea5e9", location: "#14b8a6", technology: "#6366f1",
  language: "#f59e0b", framework: "#10b981", algorithm: "#ec4899", data_structure: "#f43f5e",
  library: "#22c55e", paper: "#64748b", book: "#a16207", product: "#3b82f6", concept: "#94a3b8", custom: "#cbd5e1",
};
export const entityColor = (t: string) => ENTITY_COLOR[t] || "#94a3b8";
