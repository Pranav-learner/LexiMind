// Shared display metadata for the Flashcards UI: card-type + rating labels, deck status tones,
// and a relative-time helper. Kept in one place so the dashboard, review screen, and modals stay
// consistent.

import type { CardType, CardTypePref, DeckStatus, ReviewRating } from "../../types";

export const CARD_TYPE_META: Record<CardType, { label: string; icon: string }> = {
  basic: { label: "Q&A", icon: "❓" },
  definition: { label: "Definition", icon: "📖" },
  cloze: { label: "Cloze", icon: "▢" },
  truefalse: { label: "True/False", icon: "⚖️" },
};

export const CARD_TYPE_PREFS: Array<{ value: CardTypePref; label: string; blurb: string }> = [
  { value: "mixed", label: "Mixed", blurb: "Let AI pick the best type per fact" },
  { value: "basic", label: "Q&A", blurb: "Question → answer" },
  { value: "definition", label: "Definition", blurb: "Concept → definition" },
  { value: "cloze", label: "Cloze", blurb: "Fill-in-the-blank" },
  { value: "truefalse", label: "True/False", blurb: "Statement → true or false" },
];

// The four SM-2 grading buttons, in display order, with colors + keyboard shortcuts.
export const RATINGS: Array<{ rating: ReviewRating; label: string; color: string; key: string }> = [
  { rating: "again", label: "Again", color: "#ef4444", key: "1" },
  { rating: "hard", label: "Hard", color: "#f59e0b", key: "2" },
  { rating: "good", label: "Good", color: "#10b981", key: "3" },
  { rating: "easy", label: "Easy", color: "#0ea5e9", key: "4" },
];

export const DECK_STATUS_META: Record<DeckStatus, { label: string; tone: string }> = {
  ready: { label: "Ready", tone: "ok" },
  queued: { label: "Queued", tone: "pending" },
  processing: { label: "Generating", tone: "pending" },
  completed: { label: "Ready", tone: "ok" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "muted" },
};

export function cardTypeLabel(t: CardType): string {
  return CARD_TYPE_META[t]?.label ?? "Card";
}

export function masteryLabel(score: number): string {
  if (score >= 0.8) return "Mastered";
  if (score >= 0.5) return "Learning";
  if (score > 0) return "Seen";
  return "New";
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const past = diff >= 0;
  const s = Math.abs(Math.round(diff / 1000));
  const fmt = (n: number, u: string) => (past ? `${n}${u} ago` : `in ${n}${u}`);
  if (s < 60) return past ? "just now" : "soon";
  const m = Math.round(s / 60);
  if (m < 60) return fmt(m, "m");
  const h = Math.round(m / 60);
  if (h < 24) return fmt(h, "h");
  const d = Math.round(h / 24);
  if (d < 30) return fmt(d, "d");
  const mo = Math.round(d / 30);
  if (mo < 12) return fmt(mo, "mo");
  return fmt(Math.round(mo / 12), "y");
}
