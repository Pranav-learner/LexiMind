// A single deck in the dashboard grid: name/icon/color, card counts (new/due/mastered), a mastery
// bar, quick "Study" CTA, and a menu (open, export, delete). Generating decks show live progress.

import { useState } from "react";
import type { Deck } from "../../types";
import { DECK_STATUS_META, relativeTime } from "./constants";

interface Props {
  deck: Deck;
  onOpen: (d: Deck) => void;
  onStudy: (d: Deck) => void;
  onExport: (d: Deck) => void;
  onDelete: (d: Deck) => void;
}

export default function DeckCard({ deck, onOpen, onStudy, onExport, onDelete }: Props) {
  const [menu, setMenu] = useState(false);
  const s = deck.stats;
  const status = DECK_STATUS_META[deck.status];
  const generating = deck.status === "queued" || deck.status === "processing";
  const mastery = s && s.total ? Math.round((s.mastered / s.total) * 100) : 0;
  const dueCount = s ? s.due + s.new : 0;

  return (
    <div className="ws-card fc-deck-card" style={{ ["--deck" as string]: deck.color }}>
      <div className="fc-deck-top" onClick={() => onOpen(deck)} role="button" tabIndex={0}
           onKeyDown={(e) => e.key === "Enter" && onOpen(deck)}>
        <span className="fc-deck-icon" style={{ background: deck.color }}>{deck.icon}</span>
        <div className="fc-deck-headings">
          <h3 className="fc-deck-name">{deck.name}</h3>
          <span className="fc-deck-sub">{deck.card_count} cards · updated {relativeTime(deck.updated_at)}</span>
        </div>
        <div className="note-card-menu" onClick={(e) => e.stopPropagation()}>
          <button className="ws-icon-btn" aria-label="Deck actions" onClick={() => setMenu((o) => !o)}>⋯</button>
          {menu && (
            <div className="note-menu-pop" onMouseLeave={() => setMenu(false)}>
              <button onClick={() => { onOpen(deck); setMenu(false); }}>📂 Open</button>
              <button onClick={() => { onExport(deck); setMenu(false); }}>⬇ Export</button>
              <button className="danger" onClick={() => { onDelete(deck); setMenu(false); }}>🗑 Delete</button>
            </div>
          )}
        </div>
      </div>

      {generating ? (
        <div className="note-card-progress">
          <div className="sum-progress"><div className="sum-progress-bar" style={{ width: `${deck.progress}%` }} /></div>
          <span className="note-card-stage">{deck.stage || "Generating…"} · {deck.progress}%</span>
        </div>
      ) : (
        <>
          {deck.description && <p className="fc-deck-desc">{deck.description}</p>}
          <div className="fc-deck-stats">
            <Stat label="New" value={s?.new ?? 0} tone="new" />
            <Stat label="Due" value={s?.due ?? 0} tone="due" />
            <Stat label="Mastered" value={s?.mastered ?? 0} tone="mastered" />
          </div>
          <div className="fc-mastery-bar" title={`${mastery}% mastered`}>
            <div className="fc-mastery-fill" style={{ width: `${mastery}%` }} />
          </div>
          <div className="fc-deck-foot">
            <span className={`sum-status ${status.tone}`}>{status.label}</span>
            <button
              className="ws-btn primary fc-study-btn"
              disabled={dueCount === 0 && deck.card_count === 0}
              onClick={() => onStudy(deck)}
            >
              {dueCount > 0 ? `Study ${dueCount}` : "Study"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={`fc-stat ${tone}`}>
      <span className="fc-stat-value">{value}</span>
      <span className="fc-stat-label">{label}</span>
    </div>
  );
}
