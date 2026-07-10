// A single workspace rendered as a card. Memoized so re-rendering the dashboard grid (e.g.
// on search keystroke) doesn't re-render every untouched card.

import { memo } from "react";
import { useNavigate } from "react-router-dom";
import type { Workspace } from "../../types";

interface Props {
  workspace: Workspace;
  onEdit: (ws: Workspace) => void;
  onArchive: (ws: Workspace) => void;
  onRestore: (ws: Workspace) => void;
  onDelete: (ws: Workspace) => void;
}

function relativeTime(iso: string): string {
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

function WorkspaceCardBase({ workspace, onEdit, onArchive, onRestore, onDelete }: Props) {
  const navigate = useNavigate();
  const w = workspace;

  return (
    <div
      className="ws-card"
      style={{ ["--ws-accent" as string]: w.color }}
      onClick={() => navigate(`/workspace/${w.id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && navigate(`/workspace/${w.id}`)}
    >
      <div className="ws-card-top">
        <span className="ws-card-icon" style={{ background: w.color }}>{w.icon}</span>
        {w.is_archived && <span className="ws-badge archived">Archived</span>}
      </div>

      <h3 className="ws-card-name">{w.name}</h3>
      <p className="ws-card-desc">{w.description || "No description"}</p>

      <div className="ws-card-stats">
        <Stat label="Docs" value={w.document_count} />
        <Stat label="Chats" value={w.chat_count} />
        <Stat label="Notes" value={w.note_count} />
        <Stat label="Cards" value={w.flashcard_count} />
        <Stat label="Summaries" value={w.summary_count} />
      </div>

      <div className="ws-card-footer">
        <span className="ws-card-updated">Updated {relativeTime(w.updated_at)}</span>
        <div className="ws-card-actions" onClick={(e) => e.stopPropagation()}>
          <button className="ws-icon-btn" title="Settings" onClick={() => onEdit(w)}>⚙️</button>
          {w.is_archived ? (
            <button className="ws-icon-btn" title="Restore" onClick={() => onRestore(w)}>♻️</button>
          ) : (
            <button className="ws-icon-btn" title="Archive" onClick={() => onArchive(w)}>📥</button>
          )}
          <button className="ws-icon-btn danger" title="Delete" onClick={() => onDelete(w)}>🗑️</button>
        </div>
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

export default memo(WorkspaceCardBase);
