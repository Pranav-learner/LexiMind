// API client for the Phase-7 Module-3 Graph Reasoning & Explainable AI. Workspace-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/reasoning`;

// ---------------------------------------------------------------- types
export interface PathEdge { rel_id: string; rel_type: string; source: string; target: string; weight: number; confidence: number }
export interface ReasoningPath { nodes: string[]; chain: string; edges: PathEdge[]; length: number; path_confidence: number; weight: number }
export interface Inference { source: string; target: string; rel_type: string; confidence: number; hops: number; derivation: string; via: string[]; inferred: boolean }
export interface DependencyChain { root: string; chain: string[]; rel_types: string[]; depth: number; confidence: number; is_root_cause: boolean }
export interface ConfidenceSignal { name: string; value: number; weight: number; contribution: number; detail: string }
export interface ReasoningConfidence {
  overall: number; band: string; signals: ConfidenceSignal[]; explanation: string;
  node_confidence: Record<string, number>; edge_confidence_avg: number; path_confidence: number[];
}
export interface ReasoningResult {
  query: string;
  seeds: { id: string; name: string; type: string }[];
  paths: ReasoningPath[];
  inferences: Inference[];
  dependencies: DependencyChain[];
  root_causes: { entity: string; confidence: number; depth: number; via: string[] }[];
  confidence: ReasoningConfidence | null;
  verification: Record<string, unknown> | null;
  explanation: Record<string, unknown>;
  context_text: string;
  citations: Record<string, unknown>[];
  complexity: Record<string, number>;
  timings: Record<string, number>;
  cache_hit: boolean;
}
export interface ReasoningLog {
  id: string; query: string; seed_count: number; traversal_depth: number; paths_found: number;
  inference_count: number; dependency_chains: number; root_causes: number; reasoning_complexity: number;
  cache_hit: boolean; overall_confidence: number; confidence_band: string; verification_status: string;
  total_ms: number; created_at: string;
}
export interface InferredEdge { id: string; rel_type: string; confidence: number; source_name: string; target_name: string; derivation: string; status: string }

// ---------------------------------------------------------------- calls
export const reason = (ws: string, body: { query: string; hops?: number; directed?: boolean; verify?: boolean; dependency?: boolean }, s?: AbortSignal) =>
  apiRequest<ReasoningResult>(`${b(ws)}/reason`, { method: "POST", body, signal: s });
export const previewReasoning = (ws: string, query: string, hops = 2, s?: AbortSignal) =>
  apiRequest<Record<string, unknown>>(`${b(ws)}/preview`, { method: "POST", body: { query, hops }, signal: s });
export const rootCause = (ws: string, query: string, s?: AbortSignal) =>
  apiRequest<{ query: string; seeds: unknown[]; root_causes: { entity: string; confidence: number; depth: number }[]; dependencies: DependencyChain[] }>(
    `${b(ws)}/root-cause`, { method: "POST", body: { query }, signal: s });
export const explainReasoning = (ws: string, query: string, s?: AbortSignal) =>
  apiRequest<{ query: string; explanation: Record<string, unknown>; confidence: ReasoningConfidence | null }>(
    `${b(ws)}/explain`, { method: "POST", body: { query }, signal: s });
export const entityDependencies = (ws: string, entityId: string, s?: AbortSignal) =>
  apiRequest<{ entity: { id: string; name: string }; dependencies: DependencyChain[]; root_causes: { entity: string; depth: number }[] }>(
    `${b(ws)}/entities/${entityId}/dependencies`, { signal: s });
export const listInferred = (ws: string, s?: AbortSignal) => apiRequest<InferredEdge[]>(`${b(ws)}/inferred`, { signal: s });
export const reasoningStats = (ws: string, s?: AbortSignal) => apiRequest<Record<string, unknown>>(`${b(ws)}/stats`, { signal: s });
export const listReasoningLogs = (ws: string, s?: AbortSignal) => apiRequest<ReasoningLog[]>(`${b(ws)}/logs`, { signal: s });

// ---------------------------------------------------------------- presentation
export const confidenceColor = (v: number) => (v >= 0.75 ? "#10b981" : v >= 0.5 ? "#f59e0b" : "#ef4444");
