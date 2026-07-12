// Agent Framework API (Phase 6, Module 1) — the developer-facing agent runtime. Run an agent request,
// preview the plan, discover tools/agents, and inspect execution telemetry (graph/timeline/results).
// Types self-contained. All routes workspace-scoped, bearer-authenticated.

import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/agent`;

// ---- types -------------------------------------------------------------------------------
export interface GraphNode {
  id: string; tool: string; args: Record<string, unknown>; mode: string; depends_on: string[];
  on_failure: string; condition: string | null; retries: number; status: string; latency_ms: number;
  attempts: number; error: string | null; result_preview: string;
}
export interface ExecutionPlan {
  query: string; requires_tools: boolean; planner: string; rationale: string; estimated_cost: number;
  intents: string[]; graph: { nodes: GraphNode[] };
}
export interface ToolResult {
  node: string; tool: string; ok: boolean; output: Record<string, unknown>; context_preview: string;
  citation_count: number; error: string | null; latency_ms: number; retries: number; cached: boolean;
}
export interface TimelineEvent { seq: number; event: string; at_ms: number; [k: string]: unknown; }
export interface RunResponse {
  execution_id: string; agent: string; success: boolean; phase: string; error: string | null;
  answer: string; plan: ExecutionPlan; citations: Record<string, unknown>[]; tool_results: ToolResult[];
  timeline: TimelineEvent[]; timings: Record<string, number>;
  prompt_package: { system: string; query: string; sections: { title: string; content: string }[]; citation_count: number; rendered_preview: string; char_length: number };
  retry_count: number; tool_count: number; token_usage: number; estimated_cost: number;
  memory: Record<string, string[]>;
}
export interface ToolSpec {
  name: string; version: string; description: string; category: string; permissions: string[];
  parallel_safe: boolean; timeout_s: number; cost_weight: number; params: { name: string; type: string; required: boolean; description: string }[];
}
export interface AgentDescriptor {
  name: string; version: string; description: string; capabilities: string[]; default_tools: string[];
  status: string; implemented: boolean; health: string;
}
export interface ExecutionLog {
  id: string; agent: string; query: string; status: string; success: boolean; cancelled: boolean;
  error: string | null; planner: string; requires_tools: boolean; tool_count: number; retry_count: number;
  estimated_cost: number; planner_ms: number; tools_ms: number; llm_ms: number; total_ms: number;
  token_usage: number; created_at: string;
}

// ---- calls --------------------------------------------------------------------------------
export function runAgent(ws: string, body: { query: string; document_id?: string; allowed_tools?: string[]; granted_permissions?: string[] }, signal?: AbortSignal) {
  return apiRequest<RunResponse>(`${b(ws)}/run`, { method: "POST", body, signal });
}
export function previewPlan(ws: string, body: { query: string; document_id?: string }, signal?: AbortSignal) {
  return apiRequest<ExecutionPlan>(`${b(ws)}/plan`, { method: "POST", body, signal });
}
export const listTools = (ws: string, s?: AbortSignal) => apiRequest<ToolSpec[]>(`${b(ws)}/tools`, { signal: s });
export const listAgents = (ws: string, s?: AbortSignal) => apiRequest<AgentDescriptor[]>(`${b(ws)}/agents`, { signal: s });
export const listExecutions = (ws: string, s?: AbortSignal) => apiRequest<ExecutionLog[]>(`${b(ws)}/executions`, { signal: s });
export function retryExecution(ws: string, id: string) { return apiRequest<RunResponse>(`${b(ws)}/executions/${id}/retry`, { method: "POST" }); }

export const NODE_STATUS_COLOR: Record<string, string> = {
  ok: "#10b981", failed: "#ef4444", denied: "#f59e0b", skipped: "#94a3b8",
  cancelled: "#64748b", running: "#6366f1", pending: "#cbd5e1",
};
