// API client for the Phase-6 Module-4 Multi-Agent Orchestration platform. Workspace-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/orchestration`;

// ---------------------------------------------------------------- types
export interface TaskNode {
  id: string;
  agent: string;
  objective: string | null;
  params: Record<string, unknown>;
  depends_on: string[];
  mode: string;
  optional: boolean;
  priority: number;
  retries: number;
  timeout_s: number;
  fallback: string | null;
  forward_evidence: boolean;
  status: string;
  attempts: number;
  latency_ms: number;
  error: string | null;
  task_id: string | null;
  result_summary: string;
  recovered_by: string | null;
}
export interface TaskGraph { nodes: TaskNode[] }

export interface AgentMessage {
  seq: number;
  at_ms: number;
  sender: string;
  recipient: string;
  type: string;
  payload: Record<string, unknown>;
}

export interface NodeResult {
  node: string;
  agent: string;
  status: string;
  task_id: string | null;
  summary: string;
  attempts: number;
  latency_ms: number;
  recovered_by: string | null;
  optional: boolean;
}

export interface OrchestrationResult {
  orchestration_id: string;
  objective: string;
  workflow: string;
  status: string;
  planner: string;
  rationale: string;
  graph: TaskGraph;
  agents_used: string[];
  schedule: Record<string, number>;
  timeline: AgentMessage[];
  shared_context: Record<string, unknown>;
  output: { title: string; summary: string; markdown: string; citations: Record<string, unknown>[] } | null;
  answer: string;
  citations: Record<string, unknown>[];
  combined_verification: Record<string, unknown>;
  final_verification: Record<string, unknown> | null;
  node_results: NodeResult[];
  llm_calls: number;
  token_usage: number;
  cost_estimate: number;
  timings: Record<string, number>;
}

export interface OrchestrationLog {
  id: string;
  objective: string;
  workflow: string;
  planner: string;
  status: string;
  node_count: number;
  parallel_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  skipped_tasks: number;
  recovered_tasks: number;
  retries: number;
  llm_calls: number;
  token_usage: number;
  cost_estimate: number;
  total_ms: number;
  verification_status: string;
  verification_confidence: number;
  agents_used: string[] | null;
  created_at: string;
}
export interface OrchestrationDetail extends OrchestrationLog {
  graph: TaskGraph | null;
  messages: AgentMessage[] | null;
  node_results: NodeResult[] | null;
  output: { title: string; summary: string; markdown: string; citations: Record<string, unknown>[] } | null;
  final_verification: Record<string, unknown> | null;
}
export interface WorkflowTemplate { name: string; description: string; graph: TaskGraph }

// ---------------------------------------------------------------- calls
export const runWorkflow = (
  ws: string,
  body: { objective: string; document_ids?: string[]; workflow?: string; graph?: TaskGraph; params?: Record<string, unknown> },
  s?: AbortSignal,
) => apiRequest<OrchestrationResult>(`${b(ws)}/run`, { method: "POST", body, signal: s });

export const planWorkflow = (
  ws: string,
  body: { objective: string; document_ids?: string[]; params?: Record<string, unknown> },
  s?: AbortSignal,
) => apiRequest<{ objective: string; workflow: string; rationale: string; graph: TaskGraph }>(
  `${b(ws)}/plan`, { method: "POST", body, signal: s });

export const listTemplates = (ws: string, s?: AbortSignal) =>
  apiRequest<WorkflowTemplate[]>(`${b(ws)}/templates`, { signal: s });

export const listOrchestrations = (ws: string, s?: AbortSignal) =>
  apiRequest<OrchestrationLog[]>(`${b(ws)}`, { signal: s });

export const getOrchestration = (ws: string, id: string, s?: AbortSignal) =>
  apiRequest<OrchestrationDetail>(`${b(ws)}/${id}`, { signal: s });

export const retryOrchestration = (ws: string, id: string) =>
  apiRequest<OrchestrationResult>(`${b(ws)}/${id}/retry`, { method: "POST" });

export const orchestrationStats = (ws: string, s?: AbortSignal) =>
  apiRequest<{ orchestrations: number; completed: number; avg_total_ms: number }>(`${b(ws)}/stats`, { signal: s });

// ---------------------------------------------------------------- presentation
export const NODE_STATUS_COLOR: Record<string, string> = {
  ok: "#10b981", recovered: "#0ea5e9", running: "#6366f1", pending: "#cbd5e1",
  failed: "#ef4444", skipped: "#94a3b8", cancelled: "#64748b",
};
export const AGENT_ICON: Record<string, string> = {
  research: "🔬", writing: "📝", comparison: "⚖️", study: "🎓", verification: "🛡️",
};
export const WORKFLOW_STATUS_COLOR: Record<string, string> = {
  completed: "#10b981", partial: "#f59e0b", failed: "#ef4444", cancelled: "#64748b", running: "#6366f1",
};
