// Persistent AI Chat Workspace API (Phase 3, Module 4). Conversation + message CRUD go through
// the shared `apiRequest` wrapper. Streaming replies use a manual `fetch` POST + a ReadableStream
// reader because EventSource cannot POST a body or attach an Authorization header. All routes are
// workspace-scoped and require the bearer token.

import { apiRequest, API_BASE, getToken } from "./client";
import type {
  ChatMessage,
  ChatStreamEvent,
  Conversation,
  ConversationCreateInput,
  ConversationListParams,
  ConversationListResponse,
  ConversationUpdateInput,
  MessageListResponse,
} from "../types";

const base = (ws: string) => `/workspaces/${ws}/conversations`;

function toQuery(params: ConversationListParams): string {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.search) q.set("search", params.search);
  if (params.archived) q.set("archived", params.archived);
  if (params.pinned) q.set("pinned", params.pinned);
  if (params.sort_by) q.set("sort_by", params.sort_by);
  if (params.order) q.set("order", params.order);
  const s = q.toString();
  return s ? `?${s}` : "";
}

// ------------------------------------------------------------ conversations

export function listConversations(
  ws: string,
  params: ConversationListParams = {},
  signal?: AbortSignal,
) {
  return apiRequest<ConversationListResponse>(`${base(ws)}${toQuery(params)}`, { signal });
}

// Broad search across titles, descriptions, message content, and citation text.
export function searchConversations(
  ws: string,
  q: string,
  limit = 20,
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams({ q, limit: String(limit) }).toString();
  return apiRequest<Conversation[]>(`${base(ws)}/search?${qs}`, { signal });
}

export function createConversation(ws: string, body: ConversationCreateInput = {}) {
  return apiRequest<Conversation>(base(ws), { method: "POST", body });
}

export function getConversation(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<Conversation>(`${base(ws)}/${id}`, { signal });
}

export function updateConversation(ws: string, id: string, body: ConversationUpdateInput) {
  return apiRequest<Conversation>(`${base(ws)}/${id}`, { method: "PATCH", body });
}

export function pinConversation(ws: string, id: string) {
  return apiRequest<Conversation>(`${base(ws)}/${id}/pin`, { method: "POST" });
}
export function unpinConversation(ws: string, id: string) {
  return apiRequest<Conversation>(`${base(ws)}/${id}/unpin`, { method: "POST" });
}
export function archiveConversation(ws: string, id: string) {
  return apiRequest<Conversation>(`${base(ws)}/${id}/archive`, { method: "POST" });
}
export function restoreConversation(ws: string, id: string) {
  return apiRequest<Conversation>(`${base(ws)}/${id}/restore`, { method: "POST" });
}
export function duplicateConversation(ws: string, id: string) {
  return apiRequest<Conversation>(`${base(ws)}/${id}/duplicate`, { method: "POST" });
}
export function deleteConversation(ws: string, id: string, permanent = false) {
  return apiRequest<void>(
    `${base(ws)}/${id}${permanent ? "?permanent=true" : ""}`,
    { method: "DELETE" },
  );
}

// ----------------------------------------------------------------- messages

export function listMessages(
  ws: string,
  id: string,
  page = 1,
  pageSize = 30,
  signal?: AbortSignal,
) {
  const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) }).toString();
  return apiRequest<MessageListResponse>(`${base(ws)}/${id}/messages?${qs}`, { signal });
}

// Non-streaming send (fallback / not used by the streaming UI path).
export function sendMessage(ws: string, id: string, content: string, topK?: number) {
  return apiRequest<{ ok: boolean; conversation_id: string; user: ChatMessage; assistant: ChatMessage }>(
    `${base(ws)}/${id}/messages`,
    { method: "POST", body: { content, ...(topK != null ? { top_k: topK } : {}) } },
  );
}

// ------------------------------------------------------------------ stream

interface StreamOptions {
  onEvent: (ev: ChatStreamEvent) => void;
  signal?: AbortSignal;
  topK?: number;
}

// POST a message and parse the Server-Sent Events reply incrementally. Frames are separated by a
// blank line (\n\n); each frame has an `event: <type>` line and a `data: <json>` line. We buffer
// partial frames across reader chunks. Cancellation is driven by the caller's AbortSignal.
export async function streamMessage(
  ws: string,
  id: string,
  content: string,
  { onEvent, signal, topK }: StreamOptions,
): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${base(ws)}/${id}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ content, ...(topK != null ? { top_k: topK } : {}) }),
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `Chat request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data && typeof data === "object" && "detail" in data) detail = String(data.detail);
    } catch {
      /* ignore */
    }
    onEvent({ type: "error", data: { error: detail, message: detail } });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const flushFrame = (frame: string) => {
    const trimmed = frame.trim();
    if (!trimmed) return;
    let eventType = "message";
    const dataLines: string[] = [];
    for (const raw of trimmed.split("\n")) {
      const line = raw.trimEnd();
      if (line.startsWith("event:")) eventType = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
    }
    if (!dataLines.length) return;
    let payload: unknown;
    try {
      payload = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    switch (eventType) {
      case "user":
        onEvent({ type: "user", data: payload as ChatMessage });
        break;
      case "token":
        onEvent({ type: "token", data: payload as { text: string } });
        break;
      case "done":
        onEvent({ type: "done", data: payload as ChatMessage });
        break;
      case "error":
        onEvent({ type: "error", data: payload as { message?: string; error: string } });
        break;
      default:
        break;
    }
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      // SSE frames are separated by a blank line. Handle both \n\n and \r\n\r\n.
      while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
        const match = buffer.slice(sep).match(/^\r?\n\r?\n/);
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + (match ? match[0].length : 2));
        flushFrame(frame);
      }
    }
    if (buffer.trim()) flushFrame(buffer);
  } finally {
    reader.releaseLock();
  }
}
