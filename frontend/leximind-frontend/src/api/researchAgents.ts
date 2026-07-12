// API client for the Phase-6 Module-2 specialized agents (research / writing / comparison / study),
// the workflow engine, and task history/export. Workspace-scoped, mirrors src/api/agents.ts style.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/agent-tasks`;

// ---------------------------------------------------------------- types
export interface OutputBlock {
  type: string;
  content: unknown;
  level: number;
  label: string;
}

export interface StructuredOutput {
  title: string;
  format: string;
  summary: string;
  blocks: OutputBlock[];
  markdown: string;
  citations: Record<string, unknown>[];
  references: Record<string, unknown>[];
}

export interface AgentStep {
  phase: string;
  label: string;
  detail: string;
  ms: number;
}

export interface EvidenceItem {
  index: number;
  text: string;
  origin_tool: string;
  source_type: string;
  document_id: string | null;
  title: string | null;
  page_number: number | null;
  timespan: string | null;
  speaker_label: string | null;
  score: number;
}

export interface TaskTimings {
  planner_ms: number;
  research_ms: number;
  analysis_ms: number;
  writing_ms: number;
  total_ms: number;
}

export interface TaskResult {
  task_id: string;
  agent: string;
  task_type: string;
  objective: string;
  success: boolean;
  phase: string;
  error: string | null;
  plan: Record<string, unknown>;
  steps: AgentStep[];
  evidence: EvidenceItem[];
  knowledge_gaps: string[];
  output: StructuredOutput | null;
  citations: Record<string, unknown>[];
  timings: TaskTimings;
  tool_calls: number;
  documents_used: number;
  media_used: number;
  workspace_used: boolean;
  token_usage: number;
  estimated_cost: number;
  timeline: Record<string, unknown>[];
}

export interface TaskLog {
  id: string;
  agent: string;
  task_type: string;
  objective: string;
  status: string;
  success: boolean;
  cancelled: boolean;
  phase: string;
  error: string | null;
  workflow: string | null;
  evidence_count: number;
  citation_count: number;
  tool_calls: number;
  documents_used: number;
  media_used: number;
  workspace_used: boolean;
  planner_ms: number;
  research_ms: number;
  writing_ms: number;
  total_ms: number;
  token_usage: number;
  cost_estimate: number;
  created_at: string;
}

export interface TaskDetail extends TaskLog {
  plan: Record<string, unknown> | null;
  steps: AgentStep[] | null;
  timeline: Record<string, unknown>[] | null;
  output: StructuredOutput | null;
  knowledge_gaps: string[] | null;
  document_ids: string[] | null;
  params: Record<string, unknown> | null;
}

export interface WorkflowStepDef {
  id: string;
  task_type: string;
  description: string;
  params: Record<string, unknown>;
  depends_on: string[];
  forward_evidence: boolean;
  objective: string | null;
}

export interface WorkflowDef {
  name: string;
  description: string;
  steps: WorkflowStepDef[];
}

export interface WorkflowRunResult {
  workflow: string;
  steps: {
    step: string;
    task_type: string;
    task_id?: string;
    success?: boolean;
    phase?: string;
    summary?: string;
    description?: string;
  }[];
  final: TaskResult | null;
  final_task_id: string | null;
}

export type TaskType = "research" | "writing" | "comparison" | "study";

// ---------------------------------------------------------------- request bodies
export interface ResearchBody {
  objective: string;
  document_ids?: string[];
  top_k?: number;
  evidence_limit?: number;
  granted_permissions?: string[];
}
export interface WritingBody {
  objective: string;
  doc_type?: string;
  document_ids?: string[];
  top_k?: number;
}
export interface ComparisonBody {
  objective: string;
  document_ids?: string[];
  targets?: { label?: string; document_id?: string; topic?: string }[];
  top_k?: number;
}
export interface StudyBody {
  objective: string;
  document_ids?: string[];
  deliverables?: string[];
  subject?: string;
  granted_permissions?: string[];
}

// ---------------------------------------------------------------- calls
export const runResearch = (ws: string, body: ResearchBody, s?: AbortSignal) =>
  apiRequest<TaskResult>(`${b(ws)}/research`, { method: "POST", body, signal: s });

export const runWriting = (ws: string, body: WritingBody, s?: AbortSignal) =>
  apiRequest<TaskResult>(`${b(ws)}/writing`, { method: "POST", body, signal: s });

export const runComparison = (ws: string, body: ComparisonBody, s?: AbortSignal) =>
  apiRequest<TaskResult>(`${b(ws)}/comparison`, { method: "POST", body, signal: s });

export const runStudy = (ws: string, body: StudyBody, s?: AbortSignal) =>
  apiRequest<TaskResult>(`${b(ws)}/study`, { method: "POST", body, signal: s });

export const runWorkflow = (
  ws: string,
  name: string,
  body: { objective: string; document_ids?: string[]; params?: Record<string, unknown> },
  s?: AbortSignal,
) => apiRequest<WorkflowRunResult>(`${b(ws)}/workflows/${name}/run`, { method: "POST", body, signal: s });

export const previewTask = (
  ws: string,
  body: { task_type: TaskType; objective: string; document_ids?: string[]; params?: Record<string, unknown> },
  s?: AbortSignal,
) => apiRequest<{ task_type: string; objective: string; plan: Record<string, unknown> }>(
  `${b(ws)}/preview`, { method: "POST", body, signal: s });

export const listSpecializedAgents = (ws: string, s?: AbortSignal) =>
  apiRequest<string[]>(`${b(ws)}/agents`, { signal: s });

export const listWorkflows = (ws: string, s?: AbortSignal) =>
  apiRequest<WorkflowDef[]>(`${b(ws)}/workflows`, { signal: s });

export const listTasks = (ws: string, s?: AbortSignal) =>
  apiRequest<TaskLog[]>(`${b(ws)}`, { signal: s });

export const getTask = (ws: string, id: string, s?: AbortSignal) =>
  apiRequest<TaskDetail>(`${b(ws)}/${id}`, { signal: s });

export const retryTask = (ws: string, id: string) =>
  apiRequest<TaskResult>(`${b(ws)}/${id}/retry`, { method: "POST" });

export const cancelTask = (ws: string, id: string) =>
  apiRequest<TaskLog>(`${b(ws)}/${id}/cancel`, { method: "POST" });

export const exportTaskUrl = (ws: string, id: string, format: "markdown" | "json" = "markdown") =>
  `${b(ws)}/${id}/export?format=${format}`;

export const exportTask = (ws: string, id: string, format: "markdown" | "json" = "markdown", s?: AbortSignal) =>
  apiRequest<{ task_id: string; format: string; content: unknown; filename: string }>(
    exportTaskUrl(ws, id, format), { signal: s });

export const AGENT_META: Record<TaskType, { label: string; icon: string; blurb: string }> = {
  research: { label: "Research", icon: "🔬", blurb: "Plan, search the workspace, rank evidence, report." },
  writing: { label: "Write Report", icon: "📝", blurb: "Draft a grounded document from workspace knowledge." },
  comparison: { label: "Compare", icon: "⚖️", blurb: "Compare documents, recordings or topics." },
  study: { label: "Study", icon: "🎓", blurb: "Notes, flashcards, study guide and a learning plan." },
};

export const PHASE_COLOR: Record<string, string> = {
  planning: "#6366f1", research: "#0ea5e9", analysis: "#f59e0b",
  writing: "#10b981", done: "#10b981", failed: "#ef4444", cancelled: "#64748b",
};
