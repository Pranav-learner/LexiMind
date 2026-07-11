// Smart Notes API (Phase 3, Module 6). CRUD + list/filter + tags go through the shared
// `apiRequest` wrapper. AI generation is asynchronous: `generateNote` returns a queued/processing
// note and the caller polls GET /{id}/status until a terminal state. Autosave uses PUT
// /{id}/content with an optimistic `base_version` (a stale version → 409). The markdown export is
// fetched manually (as a Blob) because a plain <a download> cannot attach the bearer token. All
// routes are workspace-scoped and require the bearer token.

import { apiRequest, API_BASE, getToken } from "./client";
import type {
  AssistOperation,
  AssistResponse,
  Note,
  NoteCreateInput,
  NoteDetail,
  NoteGenerateInput,
  NoteListParams,
  NoteListResponse,
  NoteMetaUpdateInput,
  NoteStatus,
  Tag,
  TagListResponse,
} from "../types";

const base = (ws: string) => `/workspaces/${ws}/notes`;
const tagBase = (ws: string) => `/workspaces/${ws}/tags`;

// A note's AI generation is done once it reaches one of these states.
export const TERMINAL_STATUSES: NoteStatus[] = ["ready", "completed", "failed", "cancelled"];

export function isTerminal(status: NoteStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

function toQuery(params: NoteListParams): string {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  if (params.search) q.set("search", params.search);
  if (params.note_type) q.set("note_type", params.note_type);
  if (params.source) q.set("source", params.source);
  if (params.document_id) q.set("document_id", params.document_id);
  if (params.conversation_id) q.set("conversation_id", params.conversation_id);
  if (params.tag_id) q.set("tag_id", params.tag_id);
  if (params.status) q.set("status", params.status);
  if (params.archived) q.set("archived", params.archived);
  if (params.pinned) q.set("pinned", params.pinned);
  if (params.sort_by) q.set("sort_by", params.sort_by);
  if (params.order) q.set("order", params.order);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function listNotes(ws: string, params: NoteListParams = {}, signal?: AbortSignal) {
  return apiRequest<NoteListResponse>(`${base(ws)}${toQuery(params)}`, { signal });
}

// Manual create (201): blank / selection / paste — born ready.
export function createNote(ws: string, body: NoteCreateInput) {
  return apiRequest<NoteDetail>(base(ws), { method: "POST", body });
}

// AI generate (202): returns a queued/processing note to be polled.
export function generateNote(ws: string, body: NoteGenerateInput) {
  return apiRequest<Note>(`${base(ws)}/generate`, { method: "POST", body });
}

export function noteFromSummary(ws: string, summaryId: string) {
  return apiRequest<NoteDetail>(`${base(ws)}/from-summary/${summaryId}`, { method: "POST" });
}

export function noteFromMessage(ws: string, messageId: string) {
  return apiRequest<NoteDetail>(`${base(ws)}/from-message/${messageId}`, { method: "POST" });
}

// Lightweight poll target — status/progress/stage only.
export function getNoteStatus(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<Note>(`${base(ws)}/${id}/status`, { signal });
}

// Full detail including the editable content, sections, citations, and derived outline.
export function getNote(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<NoteDetail>(`${base(ws)}/${id}`, { signal });
}

// Autosave the content body. `base_version` enables optimistic-concurrency conflict detection.
export function saveNoteContent(
  ws: string,
  id: string,
  body: { content: string; base_version?: number; title?: string },
) {
  return apiRequest<Note>(`${base(ws)}/${id}/content`, { method: "PUT", body });
}

export function updateNote(ws: string, id: string, body: NoteMetaUpdateInput) {
  return apiRequest<Note>(`${base(ws)}/${id}`, { method: "PATCH", body });
}

export function assistNote(
  ws: string,
  id: string,
  body: { operation: AssistOperation; selection: string; instruction?: string; ground?: boolean },
) {
  return apiRequest<AssistResponse>(`${base(ws)}/${id}/assist`, { method: "POST", body });
}

export function setNoteTags(ws: string, id: string, tagIds: string[]) {
  return apiRequest<Note>(`${base(ws)}/${id}/tags`, { method: "PUT", body: { tag_ids: tagIds } });
}

export function regenerateNote(ws: string, id: string) {
  return apiRequest<Note>(`${base(ws)}/${id}/regenerate`, { method: "POST" });
}

export function cancelNote(ws: string, id: string) {
  return apiRequest<Note>(`${base(ws)}/${id}/cancel`, { method: "POST" });
}

export function duplicateNote(ws: string, id: string) {
  return apiRequest<NoteDetail>(`${base(ws)}/${id}/duplicate`, { method: "POST" });
}

export function deleteNote(ws: string, id: string, permanent = false) {
  return apiRequest<void>(
    `${base(ws)}/${id}${permanent ? "?permanent=true" : ""}`,
    { method: "DELETE" },
  );
}

// --- tags ---
export function listTags(ws: string, signal?: AbortSignal) {
  return apiRequest<TagListResponse>(tagBase(ws), { signal });
}

export function createTag(ws: string, body: { name: string; color?: string }) {
  return apiRequest<Tag>(tagBase(ws), { method: "POST", body });
}

export function updateTag(ws: string, id: string, body: { name?: string; color?: string }) {
  return apiRequest<Tag>(`${tagBase(ws)}/${id}`, { method: "PATCH", body });
}

export function deleteTag(ws: string, id: string) {
  return apiRequest<void>(`${tagBase(ws)}/${id}`, { method: "DELETE" });
}

// Fetch the rendered Markdown with the bearer token and trigger a browser download.
export async function exportNote(ws: string, id: string, filename?: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${base(ws)}/${id}/export?format=md`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || `note-${id}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

interface PollOptions {
  onUpdate?: (n: Note) => void;
  signal?: AbortSignal;
  intervalMs?: number;
}

// Poll GET /{id}/status until the note reaches a terminal state, invoking `onUpdate` on each tick.
export async function pollNoteStatus(
  ws: string,
  id: string,
  { onUpdate, signal, intervalMs = 1200 }: PollOptions = {},
): Promise<Note> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const n = await getNoteStatus(ws, id, signal);
    onUpdate?.(n);
    if (isTerminal(n.status)) return n;
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
