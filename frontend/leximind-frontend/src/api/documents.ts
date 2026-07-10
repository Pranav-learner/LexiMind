// Document Library API calls. CRUD + list/filter go through the shared `apiRequest` wrapper;
// upload uses XMLHttpRequest instead of fetch so we can report upload progress (fetch can't).
// All routes are workspace-scoped and require the bearer token.

import { apiRequest, API_BASE, getToken } from "./client";
import type {
  DocumentListParams,
  DocumentListResponse,
  LibraryDocument,
  LibraryDocumentDetail,
  UploadItemResult,
} from "../types";

function toQuery(params: DocumentListParams): string {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.search) q.set("search", params.search);
  if (params.archived) q.set("archived", params.archived);
  if (params.indexed) q.set("indexed", params.indexed);
  if (params.file_type) q.set("file_type", params.file_type);
  if (params.language) q.set("language", params.language);
  if (params.sort_by) q.set("sort_by", params.sort_by);
  if (params.order) q.set("order", params.order);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function listDocuments(
  ws: string,
  params: DocumentListParams = {},
  signal?: AbortSignal,
) {
  return apiRequest<DocumentListResponse>(
    `/workspaces/${ws}/documents${toQuery(params)}`,
    { signal },
  );
}

export function getDocument(ws: string, id: string) {
  return apiRequest<LibraryDocumentDetail>(`/workspaces/${ws}/documents/${id}`);
}

export function updateDocument(
  ws: string,
  id: string,
  values: { display_name?: string; description?: string },
) {
  return apiRequest<LibraryDocument>(`/workspaces/${ws}/documents/${id}`, {
    method: "PATCH",
    body: values,
  });
}

export function archiveDocument(ws: string, id: string) {
  return apiRequest<LibraryDocument>(`/workspaces/${ws}/documents/${id}/archive`, {
    method: "POST",
  });
}

export function restoreDocument(ws: string, id: string) {
  return apiRequest<LibraryDocument>(`/workspaces/${ws}/documents/${id}/restore`, {
    method: "POST",
  });
}

export function reindexDocument(ws: string, id: string) {
  return apiRequest<LibraryDocument>(`/workspaces/${ws}/documents/${id}/reindex`, {
    method: "POST",
  });
}

export function deleteDocument(ws: string, id: string, permanent = false) {
  return apiRequest<void>(
    `/workspaces/${ws}/documents/${id}${permanent ? "?permanent=true" : ""}`,
    { method: "DELETE" },
  );
}

// Upload a SINGLE file (one per request) so we can show per-file progress + retry.
// Uses XHR because fetch cannot report upload progress. Resolves with items[0].
export function uploadDocument(
  ws: string,
  file: File,
  onProgress?: (pct: number) => void,
): Promise<UploadItemResult> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("files", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/workspaces/${ws}/documents`);

    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
    }

    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        data = null;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        const items =
          data && typeof data === "object" && "items" in data
            ? (data as { items: UploadItemResult[] }).items
            : [];
        const item = items[0];
        if (item) resolve(item);
        else
          resolve({
            filename: file.name,
            success: false,
            error: "Upload returned no result.",
            document: null,
          });
      } else {
        const detail =
          data && typeof data === "object" && "detail" in data
            ? String((data as { detail: unknown }).detail)
            : `Upload failed (${xhr.status})`;
        reject(new Error(detail));
      }
    };

    xhr.onerror = () => reject(new Error("Network error during upload."));
    xhr.onabort = () => reject(new Error("Upload aborted."));

    xhr.send(formData);
  });
}
