// Upload + query calls. Phase 3: both now optionally carry a workspace_id so uploads land
// in a workspace and questions are scoped to it. The auth token is attached automatically
// (uploads bump the workspace document_count server-side only when authenticated).

import { API_BASE, getToken } from "./client";

export async function uploadPdf(file: File, workspaceId?: string) {
  const formData = new FormData();
  formData.append("file", file);
  if (workspaceId) formData.append("workspace_id", workspaceId);

  const token = getToken();
  const response = await fetch(`${API_BASE}/upload/pdf`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: formData,
  });

  if (!response.ok) throw new Error("PDF upload failed");
  return response.json();
}

export async function askQuestion(question: string, workspaceId?: string) {
  const token = getToken();
  const response = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ question, workspace_id: workspaceId }),
  });

  if (!response.ok) throw new Error("Query failed");
  return response.json();
}
