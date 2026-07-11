// Shared display metadata for the Smart Notes UI: note-type labels/icons, status tones, the
// AI-assist operation catalog, and a relative-time helper. Kept in one place so the dashboard,
// cards, editor, and modals stay consistent.

import type { AssistOperation, NoteStatus, NoteType } from "../../types";

export const NOTE_TYPE_META: Record<NoteType, { label: string; icon: string; blurb: string }> = {
  quick: { label: "Quick notes", icon: "⚡", blurb: "Terse, scannable bullet points." },
  study: { label: "Study notes", icon: "📚", blurb: "Overview, key points, concepts & examples." },
  detailed: { label: "Detailed notes", icon: "📖", blurb: "Thorough, section-by-section coverage." },
  chapterwise: { label: "Chapter notes", icon: "🗂️", blurb: "One block per document heading." },
  concept: { label: "Concept notes", icon: "💡", blurb: "Definition, how it works, examples." },
  revision: { label: "Revision notes", icon: "🎯", blurb: "Crisp recall for last-minute review." },
};

export const NOTE_TYPES: NoteType[] = ["quick", "study", "detailed", "chapterwise", "concept", "revision"];

export function noteTypeLabel(t: NoteType | null): string {
  return t ? NOTE_TYPE_META[t]?.label ?? "Notes" : "Note";
}

export function noteTypeIcon(t: NoteType | null): string {
  return t ? NOTE_TYPE_META[t]?.icon ?? "📝" : "📝";
}

export const STATUS_META: Record<NoteStatus, { label: string; tone: string }> = {
  ready: { label: "Ready", tone: "ok" },
  queued: { label: "Queued", tone: "pending" },
  processing: { label: "Generating", tone: "pending" },
  completed: { label: "Ready", tone: "ok" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "muted" },
};

// AI-assisted editing operations offered on a selection. `grounded` ops pull workspace evidence.
export const ASSIST_OPS: Array<{
  op: AssistOperation;
  label: string;
  icon: string;
  grounded?: boolean;
}> = [
  { op: "rewrite", label: "Rewrite", icon: "✍️" },
  { op: "expand", label: "Expand", icon: "➕", grounded: true },
  { op: "simplify", label: "Simplify", icon: "🔤" },
  { op: "grammar", label: "Fix grammar", icon: "✅" },
  { op: "examples", label: "Add examples", icon: "🧩", grounded: true },
  { op: "summarize", label: "Summarize", icon: "📄" },
  { op: "quiz", label: "Quiz questions", icon: "❓" },
  { op: "flashcards", label: "Flashcards", icon: "🃏" },
];

const TAG_COLORS = [
  "#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444",
  "#ec4899", "#8b5cf6", "#14b8a6", "#f97316", "#64748b",
];

export function suggestTagColor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return TAG_COLORS[h % TAG_COLORS.length];
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const s = Math.round(diff / 1000);
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.round(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.round(mo / 12)}y ago`;
}
