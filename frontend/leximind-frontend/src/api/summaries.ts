// AI Summaries API (Phase 3, Module 5). CRUD + list/filter go through the shared `apiRequest`
// wrapper. Generation is asynchronous: create returns a queued/processing summary and the caller
// polls GET /{id}/status until a terminal state. The markdown export is fetched manually (as a
// Blob) because a plain <a download> cannot attach the bearer token. All routes are
// workspace-scoped and require the bearer token.

import { apiRequest, API_BASE, getToken } from "./client";
import type {
  Summary,
  SummaryCreateInput,
  SummaryDetail,
  SummaryListParams,
  SummaryListResponse,
  SummaryStatus,
} from "../types";

const base = (ws: string) => `/workspaces/${ws}/summaries`;

// Generation is done once the summary reaches one of these states.
export const TERMINAL_STATUSES: SummaryStatus[] = ["completed", "failed", "cancelled"];

export function isTerminal(status: SummaryStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

function toQuery(params: SummaryListParams): string {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.search) q.set("search", params.search);
  if (params.summary_type) q.set("summary_type", params.summary_type);
  if (params.status) q.set("status", params.status);
  if (params.document_id) q.set("document_id", params.document_id);
  if (params.sort_by) q.set("sort_by", params.sort_by);
  if (params.order) q.set("order", params.order);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function listSummaries(
  ws: string,
  params: SummaryListParams = {},
  signal?: AbortSignal,
) {
  return apiRequest<SummaryListResponse>(`${base(ws)}${toQuery(params)}`, { signal });
}

// Create (202): returns a queued/processing summary to be polled.
export function createSummary(ws: string, body: SummaryCreateInput) {
  return apiRequest<Summary>(base(ws), { method: "POST", body });
}

// Lightweight poll target — status/progress/stage only.
export function getSummaryStatus(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<Summary>(`${base(ws)}/${id}/status`, { signal });
}

// Full detail including the generated sections + citations.
export function getSummary(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<SummaryDetail>(`${base(ws)}/${id}`, { signal });
}

export function renameSummary(ws: string, id: string, title: string) {
  return apiRequest<Summary>(`${base(ws)}/${id}`, { method: "PATCH", body: { title } });
}

export function regenerateSummary(ws: string, id: string) {
  return apiRequest<Summary>(`${base(ws)}/${id}/regenerate`, { method: "POST" });
}

export function cancelSummary(ws: string, id: string) {
  return apiRequest<Summary>(`${base(ws)}/${id}/cancel`, { method: "POST" });
}

export function duplicateSummary(ws: string, id: string) {
  return apiRequest<SummaryDetail>(`${base(ws)}/${id}/duplicate`, { method: "POST" });
}

export function deleteSummary(ws: string, id: string, permanent = false) {
  return apiRequest<void>(
    `${base(ws)}/${id}${permanent ? "?permanent=true" : ""}`,
    { method: "DELETE" },
  );
}

// Fetch the rendered Markdown with the bearer token and trigger a browser download.
export async function exportSummary(
  ws: string,
  id: string,
  filename?: string,
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${base(ws)}/${id}/export?format=md`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || `summary-${id}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

interface PollOptions {
  onUpdate?: (s: Summary) => void;
  signal?: AbortSignal;
  intervalMs?: number;
}

// Poll GET /{id}/status until the summary reaches a terminal state, invoking `onUpdate` on each
// tick. Resolves with the final (terminal) summary. Rejects with an AbortError if the caller's
// signal fires (either during a request or while waiting between ticks).
export async function pollSummaryStatus(
  ws: string,
  id: string,
  { onUpdate, signal, intervalMs = 1200 }: PollOptions = {},
): Promise<Summary> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const s = await getSummaryStatus(ws, id, signal);
    onUpdate?.(s);
    if (isTerminal(s.status)) return s;
    await wait(intervalMs, signal);
  }
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
  });
}
