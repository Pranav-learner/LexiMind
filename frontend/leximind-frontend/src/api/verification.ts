// API client for the Phase-6 Module-3 Verification & Reasoning Engine. Workspace-scoped; mirrors the
// agents/researchAgents client style. The verification report also arrives inline on every agent-task
// response (TaskResult.verification), so the inspector can render it without a second call.
import { apiRequest } from "./client";

const b = (ws: string) => `/workspaces/${ws}/verification`;

// ---------------------------------------------------------------- types
export interface ConfidenceSignal {
  name: string;
  value: number;
  weight: number;
  contribution: number;
  detail: string;
}
export interface ConfidenceBreakdown {
  overall: number;
  band: string;
  signals: ConfidenceSignal[];
  per_section: Record<string, number>;
  per_claim: Record<string, number>;
  explanation: string;
}
export interface ClaimVerdict {
  claim: { id: string; text: string; section: string; citation_indices: number[]; important: boolean };
  status: string;
  support_score: number;
  matched_evidence: number[];
  rationale: string;
}
export interface Contradiction {
  kind: string;
  severity: string;
  description: string;
  left: string;
  right: string;
  left_ref: number | null;
  right_ref: number | null;
  reason: string;
}
export interface CitationIssue {
  issue_type: string;
  detail: string;
  citation_index: number | null;
  claim_id: string | null;
  severity: string;
}
export interface EvidenceRef {
  index: number;
  text: string;
  source_type: string;
  document_id: string | null;
  title: string | null;
  page_number: number | null;
  timespan: string | null;
  speaker_label: string | null;
  score: number;
  modality: string;
}
export interface VerificationReport {
  status: string;
  mode: string;
  confidence: ConfidenceBreakdown;
  claims_total: number;
  counts: Record<string, number>;
  supported_ratio: number;
  claim_verdicts: ClaimVerdict[];
  contradictions: Contradiction[];
  citation_issues: CitationIssue[];
  missing_evidence: string[];
  warnings: string[];
  recommendations: string[];
  review_notes: string[];
  explanations: Record<string, unknown>;
  evidence: EvidenceRef[];
  timings: Record<string, number>;
}
export interface VerificationLog {
  id: string;
  workspace_id: string;
  execution_id: string | null;
  agent: string;
  task_type: string;
  mode: string;
  status: string;
  overall_confidence: number;
  confidence_band: string;
  claims_total: number;
  supported: number;
  weak: number;
  unsupported: number;
  conflicting: number;
  contradictions_found: number;
  citation_failures: number;
  evidence_used: number;
  warnings_count: number;
  verification_ms: number;
  review_ms: number;
  cached: boolean;
  created_at: string;
}
export interface VerificationDetail extends VerificationLog {
  report: VerificationReport | null;
}

// ---------------------------------------------------------------- calls
export const verifyAnswer = (
  ws: string,
  body: { answer: string; evidence?: unknown[]; mode?: "fast" | "thorough"; persist?: boolean },
  s?: AbortSignal,
) => apiRequest<VerificationReport>(`${b(ws)}/verify`, { method: "POST", body, signal: s });

export const verifyTask = (ws: string, taskId: string, mode: "fast" | "thorough" = "fast") =>
  apiRequest<VerificationReport>(`${b(ws)}/tasks/${taskId}/verify`, { method: "POST", body: { mode } });

export const getTaskVerification = (ws: string, taskId: string, s?: AbortSignal) =>
  apiRequest<VerificationDetail>(`${b(ws)}/tasks/${taskId}`, { signal: s });

export const getVerification = (ws: string, id: string, s?: AbortSignal) =>
  apiRequest<VerificationDetail>(`${b(ws)}/${id}`, { signal: s });

export const listVerifications = (ws: string, s?: AbortSignal) =>
  apiRequest<VerificationLog[]>(`${b(ws)}`, { signal: s });

export const verificationStats = (ws: string, s?: AbortSignal) =>
  apiRequest<{ verifications: number; verified: number; failed: number; avg_confidence: number }>(
    `${b(ws)}/stats`, { signal: s });

// ---------------------------------------------------------------- presentation helpers
export const STATUS_META: Record<string, { label: string; color: string; icon: string }> = {
  verified: { label: "Verified", color: "#10b981", icon: "✓" },
  warning: { label: "Needs review", color: "#f59e0b", icon: "!" },
  failed: { label: "Failed", color: "#ef4444", icon: "✕" },
};
export const CLAIM_STATUS_COLOR: Record<string, string> = {
  supported: "#10b981", weakly_supported: "#f59e0b", unsupported: "#ef4444", conflicting: "#dc2626",
};
export function confidenceColor(v: number): string {
  return v >= 0.75 ? "#10b981" : v >= 0.5 ? "#f59e0b" : "#ef4444";
}
