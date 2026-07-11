// Multimodal AI Workspace API (Phase 4, Module 5) — the unified capstone surface. Upload anything and
// the platform auto-runs processing + vision; explore assets, timeline, pipeline status, run AI
// actions, and read the workspace overview. All routes are workspace-scoped and require the token.

import { apiRequest, API_BASE, getToken } from "./client";
import type {
  AiActionResponse,
  AssetExplorerResponse,
  IngestResponse,
  PipelineStatus,
  WorkspaceOverview,
  WorkspaceTimelineEvent,
} from "../types";

const b = (ws: string) => `/workspaces/${ws}/ai`;

// Unified upload — multipart, auth-aware (manual fetch to attach files + bearer token).
export async function ingest(ws: string, files: File[]): Promise<IngestResponse> {
  const token = getToken();
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await fetch(`${API_BASE}${b(ws)}/ingest`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  return res.json();
}

export function getAssets(ws: string, assetType?: string, signal?: AbortSignal) {
  const q = assetType ? `?asset_type=${assetType}` : "";
  return apiRequest<AssetExplorerResponse>(`${b(ws)}/assets${q}`, { signal });
}

export function getTimeline(ws: string, signal?: AbortSignal) {
  return apiRequest<{ items: WorkspaceTimelineEvent[] }>(`${b(ws)}/timeline`, { signal });
}

export function getPipelineStatus(ws: string, documentId: string, signal?: AbortSignal) {
  return apiRequest<PipelineStatus>(`${b(ws)}/pipeline-status/${documentId}`, { signal });
}

export function runAction(ws: string, body: { action: string; document_id: string; focus?: string; count?: number }) {
  return apiRequest<AiActionResponse>(`${b(ws)}/action`, { method: "POST", body });
}

export function getOverview(ws: string, signal?: AbortSignal) {
  return apiRequest<WorkspaceOverview>(`${b(ws)}/overview`, { signal });
}

export function thumbnailUrl(path: string | null): string | null {
  if (!path) return null;
  return `${API_BASE}${path}`;
}
