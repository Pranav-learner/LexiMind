// A single AI summary rendered as a dashboard card. Memoized so re-rendering the grid (e.g. on a
// search keystroke) doesn't re-render every untouched card. Reuses the ws-card* design system and
// adds sum-* classes for the type badge, status/progress, and scope indicator. Clicking the card
// opens the viewer.

import { memo } from "react";
import type { Summary } from "../../types";
import {
  SCOPE_META,
  STATUS_META,
  relativeTime,
  summaryTypeIcon,
  summaryTypeLabel,
} from "./constants";

interface Props {
  summary: Summary;
  active?: boolean;
  onOpen: (s: Summary) => void;
  onRename: (s: Summary) => void;
  onRegenerate: (s: Summary) => void;
  onDuplicate: (s: Summary) => void;
  onDelete: (s: Summary) => void;
}

function SummaryCardBase({
  summary: s,
  active,
  onOpen,
  onRename,
  onRegenerate,
  onDuplicate,
  onDelete,
}: Props) {
  const status = STATUS_META[s.status];
  const scope = SCOPE_META[s.scope];
  const busy = s.status === "queued" || s.status === "processing";
  const failed = s.status === "failed";

  return (
    <div
      className={`ws-card sum-card${active ? " active" : ""}`}
      onClick={() => onOpen(s)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onOpen(s)}
      aria-label={`Open summary ${s.title || "Untitled"}`}
    >
      <div className="ws-card-top">
        <span className="sum-type-badge" title={summaryTypeLabel(s.summary_type)}>
          <span aria-hidden="true">{summaryTypeIcon(s.summary_type)}</span>
          {summaryTypeLabel(s.summary_type)}
        </span>
        <span className={`sum-status ${status.tone}`}>{status.label}</span>
      </div>

      <h3 className="ws-card-name sum-card-title">{s.title || "Untitled summary"}</h3>

      <div className="sum-card-meta">
        <span className="sum-scope" title={scope.label}>
          <span aria-hidden="true">{scope.icon}</span> {scope.label}
        </span>
        <span className="sum-dot" aria-hidden="true">·</span>
        <span>{s.section_count} {s.section_count === 1 ? "section" : "sections"}</span>
        {s.version > 1 && (
          <>
            <span className="sum-dot" aria-hidden="true">·</span>
            <span>v{s.version}</span>
          </>
        )}
      </div>

      {busy && (
        <div className="sum-progress-wrap">
          <div className="sum-progress" aria-label={`${s.progress}% generated`}>
            <div className="sum-progress-bar" style={{ width: `${s.progress}%` }} />
          </div>
          <span className="sum-stage">{s.stage || "Working…"} · {s.progress}%</span>
        </div>
      )}

      {failed && (
        <div className="sum-card-error" title={s.error || undefined}>
          ⚠️ {s.error || "Generation failed."}
        </div>
      )}

      <div className="ws-card-footer">
        <span className="ws-card-updated">Updated {relativeTime(s.updated_at)}</span>
        <div className="ws-card-actions" onClick={(e) => e.stopPropagation()}>
          <button className="ws-icon-btn" title="Open" aria-label="Open summary" onClick={() => onOpen(s)}>📖</button>
          <button className="ws-icon-btn" title="Rename" aria-label="Rename summary" onClick={() => onRename(s)}>✏️</button>
          <button className="ws-icon-btn" title="Regenerate" aria-label="Regenerate summary" onClick={() => onRegenerate(s)}>🔄</button>
          <button className="ws-icon-btn" title="Duplicate" aria-label="Duplicate summary" onClick={() => onDuplicate(s)}>📑</button>
          <button className="ws-icon-btn danger" title="Delete" aria-label="Delete summary" onClick={() => onDelete(s)}>🗑️</button>
        </div>
      </div>
    </div>
  );
}

export default memo(SummaryCardBase);
