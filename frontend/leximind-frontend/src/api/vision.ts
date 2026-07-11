// Vision Intelligence API (Phase 4, Module 2). Analysis is asynchronous: `analyzeDocument` returns a
// queued/processing job; poll `getVisionStatus` until terminal. Understands Module-1 visual assets
// (classification, caption, structured metadata, embeddings). All routes are workspace-scoped.

import { apiRequest, API_BASE, getToken } from "./client";
import type {
  VisionAnalysisList,
  VisionEmbedding,
  VisionJob,
  VisionJobDetail,
} from "../types";

const b = (ws: string) => `/workspaces/${ws}`;

export const TERMINAL: string[] = ["completed", "failed", "cancelled"];
export function isTerminal(status: string): boolean {
  return TERMINAL.includes(status);
}

export function analyzeDocument(ws: string, docId: string, force = false) {
  return apiRequest<VisionJob>(`${b(ws)}/documents/${docId}/vision`, { method: "POST", body: { force } });
}

export function getVisionStatus(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<VisionJob | null>(`${b(ws)}/documents/${docId}/vision`, { signal });
}

export function getAnalyses(ws: string, docId: string, imageType?: string, signal?: AbortSignal) {
  const q = imageType ? `?image_type=${imageType}` : "";
  return apiRequest<VisionAnalysisList>(`${b(ws)}/documents/${docId}/vision/analyses${q}`, { signal });
}

export function getEmbedding(ws: string, analysisId: string, includeVector = false) {
  return apiRequest<VisionEmbedding>(`${b(ws)}/vision/analyses/${analysisId}/embedding${includeVector ? "?include_vector=true" : ""}`);
}

export function getJobDetail(ws: string, jobId: string) {
  return apiRequest<VisionJobDetail>(`${b(ws)}/vision/job/${jobId}`);
}

export function retryJob(ws: string, jobId: string) {
  return apiRequest<VisionJob>(`${b(ws)}/vision/job/${jobId}/retry`, { method: "POST" });
}

export function cancelJob(ws: string, jobId: string) {
  return apiRequest<VisionJob>(`${b(ws)}/vision/job/${jobId}/cancel`, { method: "POST" });
}

// The thumbnail endpoint needs the bearer token, so fetch it as a Blob and hand back an object URL.
export async function fetchThumbnail(ws: string, analysisId: string): Promise<string | null> {
  const token = getToken();
  try {
    const res = await fetch(`${API_BASE}${b(ws)}/vision/analyses/${analysisId}/thumbnail`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!res.ok) return null;
    return URL.createObjectURL(await res.blob());
  } catch { return null; }
}

export async function pollVision(
  ws: string,
  docId: string,
  { onUpdate, signal, intervalMs = 1200 }: { onUpdate?: (j: VisionJob) => void; signal?: AbortSignal; intervalMs?: number } = {},
): Promise<VisionJob | null> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const j = await getVisionStatus(ws, docId, signal);
    if (!j) return null;
    onUpdate?.(j);
    if (isTerminal(j.status)) return j;
    await wait(intervalMs, signal);
  }
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => { clearTimeout(t); signal?.removeEventListener("abort", onAbort); reject(new DOMException("Aborted", "AbortError")); };
    const t = setTimeout(() => { signal?.removeEventListener("abort", onAbort); resolve(); }, ms);
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
  });
}
