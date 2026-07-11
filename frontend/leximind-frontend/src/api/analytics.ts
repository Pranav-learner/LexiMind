// Knowledge Dashboard & Analytics API (Phase 3, Module 9). Read-only aggregation over every module,
// cached server-side. All routes are workspace-scoped and require the bearer token.

import { apiRequest } from "./client";
import type {
  DashActivityEvent,
  DashboardOverview,
  DashCharts,
  DashDocument,
  DashInsight,
  DashKnowledge,
  DashLearning,
  DashRetrieval,
} from "../types";

const base = (ws: string) => `/workspaces/${ws}/dashboard`;

export function getDashboard(ws: string, signal?: AbortSignal) {
  return apiRequest<DashboardOverview>(base(ws), { signal });
}

export function getKnowledge(ws: string, signal?: AbortSignal) {
  return apiRequest<DashKnowledge>(`${base(ws)}/knowledge`, { signal });
}

export function getLearning(ws: string, signal?: AbortSignal) {
  return apiRequest<DashLearning>(`${base(ws)}/learning`, { signal });
}

export function getRetrieval(ws: string, signal?: AbortSignal) {
  return apiRequest<DashRetrieval>(`${base(ws)}/retrieval`, { signal });
}

export function getCharts(ws: string, signal?: AbortSignal) {
  return apiRequest<DashCharts>(`${base(ws)}/charts`, { signal });
}

export function getActivity(ws: string, params: { type?: string; limit?: number } = {}, signal?: AbortSignal) {
  const q = new URLSearchParams();
  if (params.type) q.set("type", params.type);
  if (params.limit) q.set("limit", String(params.limit));
  const s = q.toString();
  return apiRequest<{ items: DashActivityEvent[] }>(`${base(ws)}/activity${s ? `?${s}` : ""}`, { signal });
}

export function getInsights(ws: string, signal?: AbortSignal) {
  return apiRequest<{ items: DashInsight[] }>(`${base(ws)}/insights`, { signal });
}

export function getDocumentAnalytics(ws: string, signal?: AbortSignal) {
  return apiRequest<{ items: DashDocument[] }>(`${base(ws)}/documents`, { signal });
}

export function refreshDashboard(ws: string) {
  return apiRequest<DashboardOverview>(`${base(ws)}/refresh`, { method: "POST" });
}
