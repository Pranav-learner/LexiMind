// Document Library presentation constants: file-type → emoji icon, and the sort options.

import type { DocumentSortField, SortOrder } from "../../types";

// Map a document's file_type / media_type to a display emoji.
const ICONS: Record<string, string> = {
  pdf: "📄",
  doc: "📝",
  docx: "📝",
  txt: "📃",
  md: "📃",
  image: "🖼️",
  audio: "🎧",
  video: "🎬",
};

export function fileIcon(fileType?: string, mediaType?: string): string {
  const key = (fileType || mediaType || "").toLowerCase();
  return ICONS[key] || "📁";
}

export const DOCUMENT_SORTS: {
  label: string;
  field: DocumentSortField;
  order: SortOrder;
}[] = [
  { label: "Recently updated", field: "updated_at", order: "desc" },
  { label: "Newest", field: "created_at", order: "desc" },
  { label: "Name (A–Z)", field: "display_name", order: "asc" },
  { label: "Largest", field: "file_size", order: "desc" },
  { label: "Most pages", field: "page_count", order: "desc" },
  { label: "Recently indexed", field: "last_indexed_at", order: "desc" },
];

// Humanize a byte count into B / KB / MB / GB.
export function humanSize(bytes: number): string {
  if (!bytes || bytes < 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, i);
  return `${i === 0 ? value : value.toFixed(1)} ${units[i]}`;
}

// Relative-time helper (copied from WorkspaceCard so the Library reads consistently).
export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}
