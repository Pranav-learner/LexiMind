// API client for the Phase-8 Module-4 Continuous Learning & Feedback platform. Workspace-scoped.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/learning`;

// ---------------------------------------------------------------- types
export type TargetType = "answer" | "citation" | "retrieval" | "agent" | "graph" | "media" | "workspace";
export type FeedbackKind = "thumbs_up" | "thumbs_down" | "star" | "text" | "correction" | "citation";

export interface Feedback {
  id: string; target_type: string; target_id: string; kind: string; rating: number | null;
  sentiment: string; comment: string; correction: string; anonymous: boolean; created_at: string | null;
}
export interface FeedbackSummary {
  total: number; by_sentiment: Record<string, number>; by_kind: Record<string, number>;
  by_target: Record<string, number>; avg_rating: number | null; negative_rate: number; corrections: number;
}
export interface Cluster { cluster_id: string; category: string; count: number; severity: string; sample_details: string[]; keywords: string[] }
export interface Insights { total_failures: number; by_category: Record<string, number>; clusters: Cluster[]; feedback: FeedbackSummary }
export interface Recommendation {
  id: string; category: string; title: string; reason: string; evidence: Record<string, unknown>;
  expected_impact: string; confidence: number; severity: string; affected_components: string[];
  cluster_id: string | null; status: string; reviewer: string | null; review_note: string;
  reviewed_at: string | null; created_at: string | null;
}
export interface CycleResult { cycle_id: string; recommendations_generated: number; recommendation_ids: string[]; avg_confidence: number; affected_components: string[] }
export interface ImprovementReport {
  recommendation_status: Record<string, number>; by_category: Record<string, number>;
  cycles: { id: string; failures_analyzed: number; clusters: number; recommendations_generated: number; avg_confidence: number; affected_components: string[]; created_at: string | null }[];
  approved: number; rejected: number; pending: number;
}
export interface Dashboard { feedback: FeedbackSummary; insights: Insights; review: ImprovementReport; pending_recommendations: Recommendation[] }

// ---------------------------------------------------------------- calls
export const submitFeedback = (ws: string, body: { target_type: TargetType; target_id?: string; kind: FeedbackKind; rating?: number; comment?: string; correction?: string }) =>
  apiRequest<Feedback>(`${b(ws)}/feedback`, { method: "POST", body });
export const feedbackHistory = (ws: string, sentiment?: string, s?: AbortSignal) =>
  apiRequest<Feedback[]>(`${b(ws)}/feedback${sentiment ? `?sentiment=${sentiment}` : ""}`, { signal: s });
export const insights = (ws: string, s?: AbortSignal) => apiRequest<Insights>(`${b(ws)}/insights`, { signal: s });
export const runCycle = (ws: string) => apiRequest<CycleResult>(`${b(ws)}/cycle`, { method: "POST", body: {} });
export const recommendations = (ws: string, status = "pending", category?: string, s?: AbortSignal) =>
  apiRequest<Recommendation[]>(`${b(ws)}/recommendations?status=${status}${category ? `&category=${category}` : ""}`, { signal: s });
export const approve = (ws: string, id: string, note = "") => apiRequest<Recommendation>(`${b(ws)}/recommendations/${id}/approve`, { method: "POST", body: { note } });
export const reject = (ws: string, id: string, note = "") => apiRequest<Recommendation>(`${b(ws)}/recommendations/${id}/reject`, { method: "POST", body: { note } });
export const buildDataset = (ws: string, name?: string) => apiRequest<{ created: boolean; dataset_id?: string; name?: string; item_count?: number; reason?: string }>(`${b(ws)}/dataset`, { method: "POST", body: { name } });
export const report = (ws: string, s?: AbortSignal) => apiRequest<ImprovementReport>(`${b(ws)}/report`, { signal: s });
export const dashboard = (ws: string, s?: AbortSignal) => apiRequest<Dashboard>(`${b(ws)}/dashboard`, { signal: s });

// ---------------------------------------------------------------- presentation
export const CATEGORY_COLOR: Record<string, string> = {
  prompt: "#6366f1", retrieval: "#0ea5e9", agent: "#ec4899", dataset: "#14b8a6", routing: "#f59e0b",
  graph: "#10b981", context: "#8b5cf6", "": "#94a3b8",
};
export const categoryColor = (c: string) => CATEGORY_COLOR[c] || "#94a3b8";
export const SEVERITY_COLOR: Record<string, string> = { info: "#0ea5e9", warning: "#f59e0b", critical: "#ef4444" };
export const CATEGORY_LABEL: Record<string, string> = {
  missing_retrieval: "Missing retrieval", hallucination: "Hallucination", bad_citation: "Bad citation",
  slow_response: "Slow response", agent_failure: "Agent failure", low_confidence: "Low confidence",
  negative_feedback: "Negative feedback",
};
export const catLabel = (c: string) => CATEGORY_LABEL[c] || c;
export const STATUS_COLOR: Record<string, string> = { pending: "#f59e0b", approved: "#10b981", rejected: "#ef4444" };
