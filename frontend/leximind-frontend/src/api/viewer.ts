// PDF Viewer API calls (Phase 3, Module 3). Chunk fetch + reading-session progress go through
// the shared `apiRequest` wrapper. The raw file endpoint is fetched manually (as an
// ArrayBuffer / Blob) because pdf.js cannot attach the bearer token itself and because a plain
// <a download> can't send an Authorization header.

import { apiRequest, API_BASE, getToken } from "./client";
import type {
  DocumentChunksResponse,
  LibraryDocumentDetail,
  ReadingHistoryResponse,
  ReadingSession,
} from "../types";

// Fetch the raw PDF bytes with the bearer token so pdf.js can consume the ArrayBuffer directly.
export async function fetchDocumentFile(
  ws: string,
  id: string,
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/workspaces/${ws}/documents/${id}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    signal,
  });
  if (!res.ok) throw new Error(`Failed to load PDF file (${res.status})`);
  return res.arrayBuffer();
}

// Fetch the file as a Blob for a client-side download (auth-aware).
export async function downloadDocumentFile(
  ws: string,
  id: string,
  filename: string,
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/workspaces/${ws}/documents/${id}/file`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "document.pdf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function getDocumentChunks(
  ws: string,
  id: string,
  page?: number,
  signal?: AbortSignal,
): Promise<DocumentChunksResponse> {
  const q = page != null ? `?page=${page}` : "";
  return apiRequest<DocumentChunksResponse>(
    `/workspaces/${ws}/documents/${id}/chunks${q}`,
    { signal },
  );
}

// Resolve an AI citation's VECTOR document id to the real library document.
export function getDocumentByVector(
  ws: string,
  vectorDocumentId: string,
): Promise<LibraryDocumentDetail> {
  return apiRequest<LibraryDocumentDetail>(
    `/workspaces/${ws}/documents/by-vector/${vectorDocumentId}`,
  );
}

export function getReadingProgress(
  ws: string,
  id: string,
  signal?: AbortSignal,
): Promise<ReadingSession | null> {
  return apiRequest<ReadingSession | null>(
    `/workspaces/${ws}/reading/${id}/progress`,
    { signal },
  );
}

export function putReadingProgress(
  ws: string,
  id: string,
  body: { page: number; scroll_top: number; zoom: number; rotation: number },
): Promise<ReadingSession> {
  return apiRequest<ReadingSession>(`/workspaces/${ws}/reading/${id}/progress`, {
    method: "PUT",
    body,
  });
}

export function getReadingHistory(
  ws: string,
  limit?: number,
  signal?: AbortSignal,
): Promise<ReadingHistoryResponse> {
  const q = limit != null ? `?limit=${limit}` : "";
  return apiRequest<ReadingHistoryResponse>(`/workspaces/${ws}/reading/history${q}`, {
    signal,
  });
}
