// API client for the Phase-8 Module-3 AI Optimization & Cost Intelligence platform. Workspace-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/optimization`;

// ---------------------------------------------------------------- types
export type Policy =
  | "balanced" | "lowest_cost" | "highest_quality" | "fastest" | "research" | "offline" | "developer" | "enterprise";

export interface ModelSpec {
  name: string; provider: string; input_cost_per_1k: number; output_cost_per_1k: number;
  quality: number; avg_latency_ms: number; max_context: number; local: boolean; available: boolean;
}
export interface Candidate { model: string; provider: string; score: number; est_cost: number; quality: number; latency_ms: number }
export interface RetrievalPlan { top_k: number; rerank_depth: number; hybrid_alpha: number; graph_hops: number; use_graph: boolean; early_stop: boolean; use_cache: boolean; rationale: string }
export interface ContextPlan { token_budget: number; compression: string; dedup: boolean; preserve_citations: boolean; rationale: string }
export interface PromptPlan { template: string; version: string; compress: boolean; rationale: string }
export interface Recommendation { kind: string; message: string; estimated_savings: number; action: Record<string, unknown> }
export interface Profile { query: string; complexity: number; tier: string; est_context_tokens: number; est_output_tokens: number; quality_requirement: number; is_research: boolean; keywords: string[] }
export interface OptimizationPlan {
  policy: string; profile: Profile; model: ModelSpec; retrieval: RetrievalPlan; context: ContextPlan;
  prompt: PromptPlan; cache_decision: string; estimated_cost: number; estimated_latency_ms: number;
  baseline_cost: number; estimated_savings: number; recommendations: Recommendation[]; candidates: Candidate[]; rationale: string;
}
export interface RunResult {
  plan: OptimizationPlan; run_id: string; savings: number;
  result: { answer: string; cache_used: boolean; results: number; tokens: number; actual_cost: number; verification_status: string | null; quality_impact: number };
}
export interface HistoryRow {
  id: string; query: string; policy: string; tier: string; model: string; compression: string; cache_used: boolean;
  estimated_cost: number; actual_cost: number; baseline_cost: number; savings: number; tokens: number; quality_impact: number; created_at: string | null;
}
export interface CostAnalysis {
  total_tokens: number; total_cost: number; avg_cost_per_request: number;
  top_cost_sources: { source: string; cost: number; tokens: number }[];
  optimization: { runs: number; cache_hits: number; avg_savings: number; total_estimated_cost: number; total_baseline_cost: number };
}
export interface QualityPoint { model: string; cost: number; quality: number; policy: string; tier: string; savings: number; latency_ms: number; cache_used: boolean }
export interface CacheReport { layers: Record<string, Record<string, unknown>>; recommendation: string }
export interface PolicyInfo { current: Policy; available: Policy[]; resolved?: Record<string, unknown> }
export interface Dashboard { policy: PolicyInfo; cost_analysis: CostAnalysis; cache: CacheReport; recent_runs: HistoryRow[]; quality_vs_cost: QualityPoint[] }

// ---------------------------------------------------------------- calls
export const preview = (ws: string, query: string, policy?: Policy) =>
  apiRequest<OptimizationPlan>(`${b(ws)}/preview`, { method: "POST", body: { query, policy } });
export const recommendModel = (ws: string, query: string, policy?: Policy) =>
  apiRequest<{ selected: ModelSpec; candidates: Candidate[]; rationale: string; profile: Profile }>(`${b(ws)}/recommend/model`, { method: "POST", body: { query, policy } });
export const runOptimized = (ws: string, query: string, policy?: Policy) =>
  apiRequest<RunResult>(`${b(ws)}/run`, { method: "POST", body: { query, policy } });
export const dashboard = (ws: string, s?: AbortSignal) => apiRequest<Dashboard>(`${b(ws)}/dashboard`, { signal: s });
export const costAnalysis = (ws: string, s?: AbortSignal) => apiRequest<CostAnalysis>(`${b(ws)}/cost`, { signal: s });
export const history = (ws: string, s?: AbortSignal) => apiRequest<HistoryRow[]>(`${b(ws)}/history`, { signal: s });
export const cacheStats = (ws: string, s?: AbortSignal) => apiRequest<CacheReport>(`${b(ws)}/cache`, { signal: s });
export const getPolicy = (ws: string, s?: AbortSignal) => apiRequest<PolicyInfo>(`${b(ws)}/policy`, { signal: s });
export const setPolicy = (ws: string, policy: Policy) => apiRequest<PolicyInfo>(`${b(ws)}/policy`, { method: "PUT", body: { policy } });

// ---------------------------------------------------------------- presentation
export const POLICY_LABEL: Record<string, string> = {
  balanced: "Balanced", lowest_cost: "Lowest Cost", highest_quality: "Highest Quality", fastest: "Fastest",
  research: "Research", offline: "Offline", developer: "Developer", enterprise: "Enterprise",
};
export const PROVIDER_COLOR: Record<string, string> = {
  anthropic: "#d97757", openai: "#10a37f", google: "#4285f4", local: "#8b5cf6", "": "#94a3b8",
};
export const providerColor = (p: string) => PROVIDER_COLOR[p] || "#94a3b8";
export const REC_ICON: Record<string, string> = {
  reuse_cache: "♻️", model_switch: "🔀", compress_context: "🗜️", reduce_graph: "🕸️", skip_reranker: "⏭️",
};
export const recIcon = (k: string) => REC_ICON[k] || "💡";
export const TIER_COLOR: Record<string, string> = { simple: "#10b981", moderate: "#f59e0b", complex: "#ef4444" };
