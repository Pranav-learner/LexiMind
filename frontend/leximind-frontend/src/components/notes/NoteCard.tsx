// A single note in the dashboard grid. Shows title, a snippet, tags, type/status, word count,
// and quick actions (pin, favorite, archive, duplicate, delete). Clicking the body opens the
// editor. A note still generating shows a mini progress bar instead of a snippet.

import { useState } from "react";
import type { Note } from "../../types";
import { STATUS_META, noteTypeIcon, relativeTime } from "./constants";

interface Props {
  note: Note;
  active?: boolean;
  onOpen: (n: Note) => void;
  onPin: (n: Note) => void;
  onFavorite: (n: Note) => void;
  onArchive: (n: Note) => void;
  onDuplicate: (n: Note) => void;
  onDelete: (n: Note) => void;
}

export default function NoteCard({
  note, active, onOpen, onPin, onFavorite, onArchive, onDuplicate, onDelete,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const status = STATUS_META[note.status];
  const generating = note.status === "queued" || note.status === "processing";

  const snippet = note.content
    ? note.content.replace(/[#>*_`~[\]()-]/g, "").replace(/\s+/g, " ").trim().slice(0, 160)
    : note.description || "Empty note";

  return (
    <div
      className={`ws-card note-card${active ? " active" : ""}${note.is_pinned ? " pinned" : ""}`}
      onClick={() => onOpen(note)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onOpen(note)}
    >
      <div className="note-card-top">
        <span className="note-card-icon" aria-hidden="true">{noteTypeIcon(note.note_type)}</span>
        <div className="note-card-flags" onClick={(e) => e.stopPropagation()}>
          {note.is_favorite && <span title="Favorite" aria-hidden="true">⭐</span>}
          {note.is_pinned && <span title="Pinned" aria-hidden="true">📌</span>}
          <div className="note-card-menu">
            <button
              className="ws-icon-btn"
              aria-label="Note actions"
              onClick={() => setMenuOpen((o) => !o)}
            >
              ⋯
            </button>
            {menuOpen && (
              <div className="note-menu-pop" onMouseLeave={() => setMenuOpen(false)}>
                <button onClick={() => { onPin(note); setMenuOpen(false); }}>
                  {note.is_pinned ? "Unpin" : "📌 Pin"}
                </button>
                <button onClick={() => { onFavorite(note); setMenuOpen(false); }}>
                  {note.is_favorite ? "Unfavorite" : "⭐ Favorite"}
                </button>
                <button onClick={() => { onArchive(note); setMenuOpen(false); }}>
                  {note.is_archived ? "Unarchive" : "🗄 Archive"}
                </button>
                <button onClick={() => { onDuplicate(note); setMenuOpen(false); }}>📑 Duplicate</button>
                <button className="danger" onClick={() => { onDelete(note); setMenuOpen(false); }}>🗑 Delete</button>
              </div>
            )}
          </div>
        </div>
      </div>

      <h3 className="note-card-title">{note.title || "Untitled note"}</h3>

      {generating ? (
        <div className="note-card-progress">
          <div className="sum-progress"><div className="sum-progress-bar" style={{ width: `${note.progress}%` }} /></div>
          <span className="note-card-stage">{note.stage || "Generating…"}</span>
        </div>
      ) : (
        <p className="note-card-snippet">{snippet}</p>
      )}

      {note.tags.length > 0 && (
        <div className="note-card-tags">
          {note.tags.slice(0, 4).map((t) => (
            <span key={t.id} className="note-tag-chip sm" style={{ ["--tag" as string]: t.color }}>
              {t.name}
            </span>
          ))}
          {note.tags.length > 4 && <span className="note-tag-more">+{note.tags.length - 4}</span>}
        </div>
      )}

      <div className="note-card-foot">
        <span className={`sum-status ${status.tone}`}>{status.label}</span>
        <span className="note-card-meta">{note.word_count} words · {note.reading_time || 0}m</span>
        <span className="note-card-meta">{relativeTime(note.updated_at)}</span>
      </div>
    </div>
  );
}
