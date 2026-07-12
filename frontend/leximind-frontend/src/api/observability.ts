// API client for the Phase-8 Module-2 AI Observability & Monitoring platform. Workspace-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/observability`;

// ---------------------------------------------------------------- types
export interface Span {
  id: string; parent_span_id: string | null; name: string; component: string; start_ms: number;
  duration_ms: number; status: string; tokens: number; cost: number; attributes: Record<string, unknown>; error: string | null;
}
export interface WaterfallRow { name: string; component: string; offset_pct: number; width_pct: number; duration_ms: number; status: string; depth: number }
export interface TraceRow { id: string; operation: string; status: string; total_ms: number; span_count: number; token_usage: number; cost_estimate: number; error: string | null; created_at: string | null }
export interface TraceDetail extends TraceRow { spans: Span[]; waterfall: WaterfallRow[] }
export interface TelemetryEvent { source: string; id: string; workspace_id: string; operation: string; latency_ms: number; tokens: number; cost: number; status: string; created_at: string | null }
export interface LatencyHist { count: number; mean: number; p50: number; p95: number; p99: number; max: number }
export interface Metrics {
  requests: number; errors: number; error_rate: number; latency_ms: LatencyHist; tokens_total: number; cost_total: number;
  by_source: Record<string, { count: number; errors: number; mean_ms: number; p95_ms: number; error_rate: number; tokens: number; cost: number }>;
  by_source_totals?: Record<string, number>;
}
export interface CostReport {
  total_tokens: number; total_cost: number; avg_tokens_per_request: number; avg_cost_per_request: number;
  by_source: Record<string, { tokens: number; cost: number; count: number }>;
  top_cost_operations: { operation: string; tokens: number; cost: number; count: number }[];
}
export interface Health { status: string; checks: Record<string, { status: string; detail: string }> }
export interface AlertRule { id: string; name: string; metric: string; comparator: string; threshold: number; severity: string; enabled: boolean }
export interface FiredAlert { rule_id: string | null; rule_name: string; metric: string; value: number; threshold: number; severity: string; message: string }
export interface AlertEvent { id: string; rule_id: string; metric: string; value: number; threshold: number; severity: string; message: string; created_at: string | null }
export interface Dashboard { metrics: Metrics; cost: CostReport; health: Health; active_alerts: FiredAlert[]; recent_traces: TraceRow[]; recent_events: TelemetryEvent[] }

// ---------------------------------------------------------------- calls
export const dashboard = (ws: string, s?: AbortSignal) => apiRequest<Dashboard>(`${b(ws)}/dashboard`, { signal: s });
export const events = (ws: string, source?: string, s?: AbortSignal) =>
  apiRequest<TelemetryEvent[]>(`${b(ws)}/events${source ? `?source=${source}` : ""}`, { signal: s });
export const metrics = (ws: string, s?: AbortSignal) => apiRequest<Metrics>(`${b(ws)}/metrics`, { signal: s });
export const costReport = (ws: string, s?: AbortSignal) => apiRequest<CostReport>(`${b(ws)}/cost`, { signal: s });
export const health = (ws: string, s?: AbortSignal) => apiRequest<Health>(`${b(ws)}/health`, { signal: s });
export const listTraces = (ws: string, s?: AbortSignal) => apiRequest<TraceRow[]>(`${b(ws)}/traces`, { signal: s });
export const getTrace = (ws: string, id: string, s?: AbortSignal) => apiRequest<TraceDetail>(`${b(ws)}/traces/${id}`, { signal: s });
export const traceQuery = (ws: string, question: string) => apiRequest<TraceDetail & { answer: string }>(`${b(ws)}/trace-query`, { method: "POST", body: { question } });
export const listRules = (ws: string, s?: AbortSignal) => apiRequest<AlertRule[]>(`${b(ws)}/alerts/rules`, { signal: s });
export const createRule = (ws: string, body: { name: string; metric: string; comparator: string; threshold: number; severity: string }) =>
  apiRequest<AlertRule>(`${b(ws)}/alerts/rules`, { method: "POST", body });
export const deleteRule = (ws: string, id: string) => apiRequest<Record<string, unknown>>(`${b(ws)}/alerts/rules/${id}`, { method: "DELETE" });
export const evaluateAlerts = (ws: string) => apiRequest<{ metrics: Record<string, number>; fired: FiredAlert[]; fired_count: number }>(`${b(ws)}/alerts/evaluate`, { method: "POST", body: {} });
export const alertHistory = (ws: string, s?: AbortSignal) => apiRequest<AlertEvent[]>(`${b(ws)}/alerts`, { signal: s });

// ---------------------------------------------------------------- presentation
export const COMPONENT_COLOR: Record<string, string> = {
  retrieval: "#0ea5e9", graph: "#10b981", context_engineering: "#f59e0b", answer_service: "#6366f1",
  verification: "#8b5cf6", agent: "#ec4899", "": "#94a3b8",
};
export const componentColor = (c: string) => COMPONENT_COLOR[c] || "#94a3b8";
export const HEALTH_COLOR: Record<string, string> = { ok: "#10b981", degraded: "#f59e0b", down: "#ef4444" };
export const SEVERITY_COLOR: Record<string, string> = { info: "#0ea5e9", warning: "#f59e0b", critical: "#ef4444" };
export const SOURCE_COLOR: Record<string, string> = {
  trace: "#6366f1", retrieval: "#0ea5e9", temporal_retrieval: "#14b8a6", memory_retrieval: "#22c55e",
  graph_build: "#a16207", graph_reasoning: "#ec4899", agent_run: "#f43f5e", agent_task: "#f59e0b",
  orchestration: "#8b5cf6", verification: "#0891b2", evaluation: "#64748b",
};
export const sourceColor = (s: string) => SOURCE_COLOR[s] || "#94a3b8";
