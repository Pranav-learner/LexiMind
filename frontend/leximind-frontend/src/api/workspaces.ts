import { apiRequest } from "./client";
import type {
  ListParams,
  Workspace,
  WorkspaceFormValues,
  WorkspaceListResponse,
} from "../types";

function toQuery(params: ListParams): string {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.search) q.set("search", params.search);
  if (params.archived) q.set("archived", params.archived);
  if (params.sort_by) q.set("sort_by", params.sort_by);
  if (params.order) q.set("order", params.order);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function listWorkspaces(params: ListParams = {}, signal?: AbortSignal) {
  return apiRequest<WorkspaceListResponse>(`/workspaces${toQuery(params)}`, { signal });
}

export function getWorkspace(id: string) {
  return apiRequest<Workspace>(`/workspaces/${id}`);
}

export function createWorkspace(values: WorkspaceFormValues) {
  return apiRequest<Workspace>("/workspaces", { method: "POST", body: values });
}

export function updateWorkspace(id: string, values: Partial<WorkspaceFormValues>) {
  return apiRequest<Workspace>(`/workspaces/${id}`, { method: "PATCH", body: values });
}

export function archiveWorkspace(id: string) {
  return apiRequest<Workspace>(`/workspaces/${id}/archive`, { method: "POST" });
}

export function restoreWorkspace(id: string) {
  return apiRequest<Workspace>(`/workspaces/${id}/restore`, { method: "POST" });
}

export function deleteWorkspace(id: string, permanent = false) {
  return apiRequest<void>(`/workspaces/${id}${permanent ? "?permanent=true" : ""}`, {
    method: "DELETE",
  });
}
