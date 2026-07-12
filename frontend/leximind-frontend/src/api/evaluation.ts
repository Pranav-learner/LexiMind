// API client for the Phase-8 Module-1 AI Evaluation & Benchmarking framework. Workspace-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/evaluation`;

// ---------------------------------------------------------------- types
export interface Dataset {
  id: string; name: string; version: number; description: string | null; tags: string[];
  item_count: number; difficulty_distribution: Record<string, number>;
}
export interface Pipeline { name: string; version: string; kind: string }
export interface MetricDelta { metric: string; current: number; baseline: number; delta: number; rel_change: number; verdict: string }
export interface RegressionReport { status: string; regressed: MetricDelta[]; improved: MetricDelta[]; deltas: MetricDelta[]; regression_count: number; improvement_count: number }
export interface Gate { passed: boolean; reasons: string[] }
export interface RunLog {
  id: string; dataset_id: string; dataset_version: number; pipeline: string; pipeline_version: string;
  model: string; label: string | null; status: string; metrics: Record<string, number>; item_count: number;
  failed_items: number; duration_ms: number; cost_estimate: number; token_usage: number; judge_used: boolean;
  baseline_run_id: string | null; regression_status: string; gate_passed: boolean | null; created_at: string | null;
}
export interface RunResult extends RunLog {
  regression: RegressionReport | null; gate: Gate;
  items: { item_id: string; question: string; output: Record<string, unknown>; metrics: Record<string, number>; judgment: Record<string, unknown> | null }[];
}
export interface Comparison { a_label: string; b_label: string; winner: string; a_wins: number; b_wins: number; per_metric: MetricDelta[] }

// ---------------------------------------------------------------- calls
export const listDatasets = (ws: string, s?: AbortSignal) => apiRequest<Dataset[]>(`${b(ws)}/datasets`, { signal: s });
export const createDataset = (ws: string, body: { name: string; description?: string; items: unknown[] }) =>
  apiRequest<Dataset>(`${b(ws)}/datasets`, { method: "POST", body });
export const exportDataset = (ws: string, id: string, s?: AbortSignal) =>
  apiRequest<Record<string, unknown>>(`${b(ws)}/datasets/${id}/export`, { signal: s });
export const listPipelines = (ws: string, s?: AbortSignal) => apiRequest<Pipeline[]>(`${b(ws)}/pipelines`, { signal: s });
export const runBenchmark = (ws: string, body: { dataset_id: string; pipeline: string; use_judge?: boolean; label?: string; thresholds?: Record<string, number> }, s?: AbortSignal) =>
  apiRequest<RunResult>(`${b(ws)}/run`, { method: "POST", body, signal: s });
export const listRuns = (ws: string, s?: AbortSignal) => apiRequest<RunLog[]>(`${b(ws)}/runs`, { signal: s });
export const getRun = (ws: string, id: string, s?: AbortSignal) => apiRequest<RunResult & { report: Record<string, unknown> }>(`${b(ws)}/runs/${id}`, { signal: s });
export const compareRuns = (ws: string, a: string, bb: string) =>
  apiRequest<{ a: RunLog; b: RunLog; comparison: Comparison }>(`${b(ws)}/compare`, { method: "POST", body: { a_run_id: a, b_run_id: bb } });
export const dashboard = (ws: string, s?: AbortSignal) =>
  apiRequest<{ total_runs: number; datasets: number; regressions: number; gate_failures: number; recent: RunLog[]; cache: Record<string, unknown> }>(`${b(ws)}/dashboard`, { signal: s });

// ---------------------------------------------------------------- presentation
export const VERDICT_COLOR: Record<string, string> = { improved: "#10b981", stable: "#94a3b8", regressed: "#ef4444" };
export const STATUS_COLOR: Record<string, string> = { improved: "#10b981", stable: "#0ea5e9", regressed: "#ef4444", none: "#94a3b8" };
export function metricColor(name: string, v: number): string {
  const lowerBetter = ["latency_ms", "token_usage", "context_size", "hallucination_rate", "cost_estimate"].includes(name);
  if (lowerBetter) return v <= 0 ? "#10b981" : "#334155";
  return v >= 0.7 ? "#10b981" : v >= 0.4 ? "#f59e0b" : "#ef4444";
}
