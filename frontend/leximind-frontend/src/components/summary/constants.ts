// AI Summaries presentation constants: the selectable summary types (with icon + blurb), the
// status → color/label map used by badges, sort options, and small helpers. Relative-time /
// scope helpers are shared with the Document Library where practical.

import type {
  SummaryScope,
  SummarySortField,
  SummaryStatus,
  SummaryType,
  SortOrder,
} from "../../types";

export interface SummaryTypeOption {
  key: SummaryType;
  label: string;
  description: string;
  icon: string;
}

export const SUMMARY_TYPES: SummaryTypeOption[] = [
  { key: "quick", label: "Quick", description: "A short TL;DR in a few sentences.", icon: "⚡" },
  { key: "standard", label: "Standard", description: "A balanced overview of the key points.", icon: "📄" },
  { key: "detailed", label: "Detailed", description: "An in-depth, comprehensive walkthrough.", icon: "📚" },
  { key: "bullet", label: "Bullet points", description: "Key takeaways as a scannable list.", icon: "🔸" },
  { key: "chapterwise", label: "Chapter-wise", description: "A section-by-section breakdown.", icon: "🗂️" },
];

const TYPE_BY_KEY: Record<SummaryType, SummaryTypeOption> = SUMMARY_TYPES.reduce(
  (acc, t) => {
    acc[t.key] = t;
    return acc;
  },
  {} as Record<SummaryType, SummaryTypeOption>,
);

export function summaryTypeIcon(t: SummaryType): string {
  return TYPE_BY_KEY[t]?.icon || "📄";
}

export function summaryTypeLabel(t: SummaryType): string {
  return TYPE_BY_KEY[t]?.label || t;
}

// Status → { label, tone }. Tone drives the badge / progress color class.
export const STATUS_META: Record<SummaryStatus, { label: string; tone: string }> = {
  queued: { label: "Queued", tone: "processing" },
  processing: { label: "Generating…", tone: "processing" },
  completed: { label: "Ready", tone: "ready" },
  failed: { label: "Failed", tone: "failed" },
  cancelled: { label: "Cancelled", tone: "muted" },
};

// Scope → { label, icon } for the little source indicator on cards / viewer.
export const SCOPE_META: Record<SummaryScope, { label: string; icon: string }> = {
  document: { label: "Single document", icon: "📄" },
  multi: { label: "Multiple documents", icon: "🗃️" },
  workspace: { label: "Whole workspace", icon: "🗂️" },
};

export const SUMMARY_SORTS: {
  label: string;
  field: SummarySortField;
  order: SortOrder;
}[] = [
  { label: "Recently updated", field: "updated_at", order: "desc" },
  { label: "Newest", field: "created_at", order: "desc" },
  { label: "Oldest", field: "created_at", order: "asc" },
  { label: "Title (A–Z)", field: "title", order: "asc" },
];

// Relative-time helper shared with the Document Library.
export { relativeTime } from "../document/constants";
