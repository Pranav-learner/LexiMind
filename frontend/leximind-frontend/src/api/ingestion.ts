// Multimodal Document Processing API (Phase 4, Module 1). Processing is asynchronous: `processDocument`
// returns a queued/processing job; poll `getProcessingStatus` until a terminal state. All routes are
// workspace-scoped and require the bearer token.

import { apiRequest } from "./client";
import type {
  ExtractedAssets,
  MultimodalChunk,
  OcrStatus,
  ProcessingJob,
  ProcessingJobDetail,
} from "../types";

const b = (ws: string) => `/workspaces/${ws}`;

export const TERMINAL: string[] = ["completed", "failed", "cancelled"];
export function isTerminal(status: string): boolean {
  return TERMINAL.includes(status);
}

export function processDocument(ws: string, docId: string, force = false) {
  return apiRequest<ProcessingJob>(`${b(ws)}/documents/${docId}/process`, { method: "POST", body: { force } });
}

export function getProcessingStatus(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<ProcessingJob | null>(`${b(ws)}/documents/${docId}/processing`, { signal });
}

export function getAssets(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<ExtractedAssets>(`${b(ws)}/documents/${docId}/assets`, { signal });
}

export function getOcr(ws: string, docId: string, signal?: AbortSignal) {
  return apiRequest<OcrStatus>(`${b(ws)}/documents/${docId}/ocr`, { signal });
}

export function getMultimodalChunks(ws: string, docId: string, chunkType?: string, signal?: AbortSignal) {
  const q = chunkType ? `?chunk_type=${chunkType}` : "";
  return apiRequest<MultimodalChunk[]>(`${b(ws)}/documents/${docId}/multimodal-chunks${q}`, { signal });
}

export function getJobDetail(ws: string, jobId: string, signal?: AbortSignal) {
  return apiRequest<ProcessingJobDetail>(`${b(ws)}/processing/${jobId}`, { signal });
}

export function retryJob(ws: string, jobId: string) {
  return apiRequest<ProcessingJob>(`${b(ws)}/processing/${jobId}/retry`, { method: "POST" });
}

export function cancelJob(ws: string, jobId: string) {
  return apiRequest<ProcessingJob>(`${b(ws)}/processing/${jobId}/cancel`, { method: "POST" });
}

// Poll document processing until terminal.
export async function pollProcessing(
  ws: string,
  docId: string,
  { onUpdate, signal, intervalMs = 1200 }: { onUpdate?: (j: ProcessingJob) => void; signal?: AbortSignal; intervalMs?: number } = {},
): Promise<ProcessingJob | null> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const j = await getProcessingStatus(ws, docId, signal);
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
