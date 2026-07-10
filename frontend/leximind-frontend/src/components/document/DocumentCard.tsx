// A single library document rendered as a card. Memoized so re-rendering the grid (e.g. on a
// search keystroke) doesn't re-render every untouched card. Reuses the ws-card* design system
// and adds a few doc-* classes for the status badge / progress bar.

import { memo } from "react";
import type { LibraryDocument } from "../../types";
import { fileIcon, humanSize, relativeTime } from "./constants";

interface Props {
  doc: LibraryDocument;
  view: "grid" | "list";
  onOpen: (doc: LibraryDocument) => void;
  onView: (doc: LibraryDocument) => void;
  onRename: (doc: LibraryDocument) => void;
  onArchive: (doc: LibraryDocument) => void;
  onRestore: (doc: LibraryDocument) => void;
  onReindex: (doc: LibraryDocument) => void;
  onDelete: (doc: LibraryDocument) => void;
}

// Maps a document's processing + indexing state to a badge {label, tone}.
function statusBadge(d: LibraryDocument): { label: string; tone: string } {
  if (d.processing_status === "failed" || d.indexing_status === "failed")
    return { label: "Failed", tone: "failed" };
  if (d.processing_status === "processing" || d.processing_status === "uploaded")
    return { label: d.processing_stage.replace(/_/g, " "), tone: "processing" };
  if (d.indexing_status === "indexed" || d.processing_status === "ready")
    return { label: d.indexing_status === "stale" ? "Stale" : "Ready", tone: "ready" };
  if (d.indexing_status === "stale") return { label: "Stale", tone: "processing" };
  return { label: d.processing_status, tone: "processing" };
}

function DocumentCardBase({
  doc,
  view,
  onOpen,
  onView,
  onRename,
  onArchive,
  onRestore,
  onReindex,
  onDelete,
}: Props) {
  const d = doc;
  const badge = statusBadge(d);
  const isProcessing = badge.tone === "processing";
  const icon = fileIcon(d.file_type, d.media_type);

  const actions = (
    <div className="ws-card-actions" onClick={(e) => e.stopPropagation()}>
      <button className="ws-icon-btn" title="Open in viewer" aria-label="Open in viewer" onClick={() => onView(d)}>📖</button>
      <button className="ws-icon-btn" title="Open details" aria-label="Open details" onClick={() => onOpen(d)}>👁️</button>
      <button className="ws-icon-btn" title="Rename" aria-label="Rename" onClick={() => onRename(d)}>✏️</button>
      <button className="ws-icon-btn" title="Reindex" aria-label="Reindex" onClick={() => onReindex(d)}>🔄</button>
      {d.is_archived ? (
        <button className="ws-icon-btn" title="Restore" aria-label="Restore" onClick={() => onRestore(d)}>♻️</button>
      ) : (
        <button className="ws-icon-btn" title="Archive" aria-label="Archive" onClick={() => onArchive(d)}>📥</button>
      )}
      <button className="ws-icon-btn danger" title="Delete" aria-label="Delete" onClick={() => onDelete(d)}>🗑️</button>
    </div>
  );

  const statusEl = (
    <span className={`doc-status ${badge.tone}`}>{badge.label}</span>
  );

  const progressBar = isProcessing && (
    <div className="doc-progress" aria-label={`${d.upload_progress}% processed`}>
      <div className="doc-progress-bar" style={{ width: `${d.upload_progress}%` }} />
    </div>
  );

  if (view === "list") {
    return (
      <div
        className="doc-row"
        onClick={() => onView(d)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && onView(d)}
      >
        <span className="doc-row-icon">{icon}</span>
        <div className="doc-row-main">
          <div className="doc-row-name">
            {d.display_name || d.filename}
            {d.is_archived && <span className="ws-badge archived">Archived</span>}
          </div>
          <div className="doc-row-sub">{d.filename}</div>
        </div>
        <div className="doc-row-meta">
          <span>{d.page_count} pg</span>
          <span>{d.chunk_count} chunks</span>
          <span>{humanSize(d.file_size)}</span>
        </div>
        <div className="doc-row-status">
          {statusEl}
          {progressBar}
        </div>
        <span className="doc-row-updated">{relativeTime(d.created_at)}</span>
        {actions}
      </div>
    );
  }

  return (
    <div
      className="ws-card doc-card"
      onClick={() => onView(d)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onView(d)}
    >
      <div className="ws-card-top">
        <span className="ws-card-icon doc-card-icon">{icon}</span>
        {d.is_archived && <span className="ws-badge archived">Archived</span>}
      </div>

      <h3 className="ws-card-name">{d.display_name || d.filename}</h3>
      <p className="ws-card-desc doc-filename">{d.filename}</p>

      <div className="ws-card-stats">
        <Stat label="Pages" value={d.page_count} />
        <Stat label="Chunks" value={d.chunk_count} />
        <Stat label="Words" value={d.word_count} />
      </div>

      <div className="doc-card-status">
        {statusEl}
        {d.embedding_model && <span className="doc-model">{d.embedding_model}</span>}
      </div>
      {progressBar}

      <div className="ws-card-footer">
        <span className="ws-card-updated">Added {relativeTime(d.created_at)}</span>
        {actions}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="ws-stat">
      <span className="ws-stat-value">{value}</span>
      <span className="ws-stat-label">{label}</span>
    </div>
  );
}

export default memo(DocumentCardBase);
