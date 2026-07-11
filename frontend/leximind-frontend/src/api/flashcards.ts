// AI Flashcards & Active Recall API (Phase 3, Module 7). Deck/card CRUD, async AI generation
// (poll GET /decks/{id}/status), SM-2 review queue + submit, learning analytics, and export. All
// routes are workspace-scoped and require the bearer token.

import { apiRequest, API_BASE, getToken } from "./client";
import type {
  CardCreateInput,
  Deck,
  DeckGenerateInput,
  DeckListParams,
  DeckListResponse,
  DeckStats,
  Flashcard,
  FlashcardDetail,
  FlashcardListResponse,
  LearningAnalytics,
  ReviewQueue,
  ReviewRating,
  ReviewResult,
} from "../types";

const b = (ws: string) => `/workspaces/${ws}`;

export const TERMINAL_DECK_STATUSES: string[] = ["ready", "completed", "failed", "cancelled"];
export function isTerminal(status: string): boolean {
  return TERMINAL_DECK_STATUSES.includes(status);
}

function deckQuery(p: DeckListParams): string {
  const q = new URLSearchParams();
  if (p.page) q.set("page", String(p.page));
  if (p.page_size) q.set("page_size", String(p.page_size));
  if (p.search) q.set("search", p.search);
  if (p.archived) q.set("archived", p.archived);
  if (p.sort_by) q.set("sort_by", p.sort_by);
  if (p.order) q.set("order", p.order);
  const s = q.toString();
  return s ? `?${s}` : "";
}

// --- decks ---
export function listDecks(ws: string, params: DeckListParams = {}, signal?: AbortSignal) {
  return apiRequest<DeckListResponse>(`${b(ws)}/decks${deckQuery(params)}`, { signal });
}
export function createDeck(ws: string, body: { name?: string; description?: string; color?: string; icon?: string }) {
  return apiRequest<Deck>(`${b(ws)}/decks`, { method: "POST", body });
}
export function generateDeck(ws: string, body: DeckGenerateInput) {
  return apiRequest<Deck>(`${b(ws)}/decks/generate`, { method: "POST", body });
}
export function deckFromNote(ws: string, noteId: string, count?: number) {
  return apiRequest<Deck>(`${b(ws)}/decks/from-note/${noteId}${count ? `?count=${count}` : ""}`, { method: "POST" });
}
export function deckFromSummary(ws: string, summaryId: string, count?: number) {
  return apiRequest<Deck>(`${b(ws)}/decks/from-summary/${summaryId}${count ? `?count=${count}` : ""}`, { method: "POST" });
}
export function deckFromChat(ws: string, conversationId: string, count?: number) {
  return apiRequest<Deck>(`${b(ws)}/decks/from-chat/${conversationId}${count ? `?count=${count}` : ""}`, { method: "POST" });
}
export function getDeck(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<Deck>(`${b(ws)}/decks/${id}`, { signal });
}
export function getDeckStatus(ws: string, id: string, signal?: AbortSignal) {
  return apiRequest<Deck>(`${b(ws)}/decks/${id}/status`, { signal });
}
export function updateDeck(ws: string, id: string, body: Record<string, unknown>) {
  return apiRequest<Deck>(`${b(ws)}/decks/${id}`, { method: "PATCH", body });
}
export function regenerateDeck(ws: string, id: string, count?: number) {
  return apiRequest<Deck>(`${b(ws)}/decks/${id}/regenerate${count ? `?count=${count}` : ""}`, { method: "POST" });
}
export function cancelDeck(ws: string, id: string) {
  return apiRequest<Deck>(`${b(ws)}/decks/${id}/cancel`, { method: "POST" });
}
export function deleteDeck(ws: string, id: string, permanent = false) {
  return apiRequest<void>(`${b(ws)}/decks/${id}${permanent ? "?permanent=true" : ""}`, { method: "DELETE" });
}
export function getDeckStats(ws: string, id: string) {
  return apiRequest<DeckStats>(`${b(ws)}/decks/${id}/stats`);
}

// --- cards ---
export function listCards(ws: string, params: { deck_id?: string; page?: number; page_size?: number; search?: string; card_type?: string; status?: string; favorite?: boolean; sort_by?: string; order?: string } = {}, signal?: AbortSignal) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== "") q.set(k, String(v)); });
  const s = q.toString();
  return apiRequest<FlashcardListResponse>(`${b(ws)}/flashcards${s ? `?${s}` : ""}`, { signal });
}
export function createCard(ws: string, body: CardCreateInput) {
  return apiRequest<FlashcardDetail>(`${b(ws)}/flashcards`, { method: "POST", body });
}
export function getCard(ws: string, id: string) {
  return apiRequest<FlashcardDetail>(`${b(ws)}/flashcards/${id}`);
}
export function updateCard(ws: string, id: string, body: Record<string, unknown>) {
  return apiRequest<Flashcard>(`${b(ws)}/flashcards/${id}`, { method: "PATCH", body });
}
export function suspendCard(ws: string, id: string) {
  return apiRequest<Flashcard>(`${b(ws)}/flashcards/${id}/suspend`, { method: "POST" });
}
export function unsuspendCard(ws: string, id: string) {
  return apiRequest<Flashcard>(`${b(ws)}/flashcards/${id}/unsuspend`, { method: "POST" });
}
export function resetCard(ws: string, id: string) {
  return apiRequest<Flashcard>(`${b(ws)}/flashcards/${id}/reset`, { method: "POST" });
}
export function deleteCard(ws: string, id: string) {
  return apiRequest<void>(`${b(ws)}/flashcards/${id}`, { method: "DELETE" });
}

// --- review (SRS) ---
export function getReviewQueue(ws: string, params: { deck_id?: string; limit?: number; new_limit?: number } = {}, signal?: AbortSignal) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined) q.set(k, String(v)); });
  const s = q.toString();
  return apiRequest<ReviewQueue>(`${b(ws)}/review${s ? `?${s}` : ""}`, { signal });
}
export function submitReview(ws: string, cardId: string, rating: ReviewRating, responseTimeMs = 0) {
  return apiRequest<ReviewResult>(`${b(ws)}/flashcards/${cardId}/review`, {
    method: "POST",
    body: { rating, response_time_ms: responseTimeMs },
  });
}

// --- analytics ---
export function getAnalytics(ws: string, days = 30, signal?: AbortSignal) {
  return apiRequest<LearningAnalytics>(`${b(ws)}/analytics?days=${days}`, { signal });
}

// --- export (blob download, auth-aware) ---
export async function exportDeck(ws: string, id: string, format: "csv" | "md" = "csv", filename?: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${b(ws)}/decks/${id}/export?format=${format}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new Error(`Export failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || `deck-${id}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Poll a deck's generation to a terminal state.
export async function pollDeckStatus(
  ws: string,
  id: string,
  { onUpdate, signal, intervalMs = 1200 }: { onUpdate?: (d: Deck) => void; signal?: AbortSignal; intervalMs?: number } = {},
): Promise<Deck> {
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const d = await getDeckStatus(ws, id, signal);
    onUpdate?.(d);
    if (isTerminal(d.status)) return d;
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
