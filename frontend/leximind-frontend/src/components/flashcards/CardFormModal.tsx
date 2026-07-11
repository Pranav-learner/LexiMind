// Create or edit a single flashcard (front / back / hint / type). Used by the deck view.

import { useState } from "react";
import type { CardType, Flashcard } from "../../types";
import { CARD_TYPE_META } from "./constants";

interface Props {
  card?: Flashcard | null;          // present → edit mode
  submitting: boolean;
  error: string | null;
  onSubmit: (data: { front: string; back: string; hint: string; card_type: CardType }) => void;
  onClose: () => void;
}

const TYPES: CardType[] = ["basic", "definition", "cloze", "truefalse"];

export default function CardFormModal({ card, submitting, error, onSubmit, onClose }: Props) {
  const [front, setFront] = useState(card?.front ?? "");
  const [back, setBack] = useState(card?.back ?? "");
  const [hint, setHint] = useState(card?.hint ?? "");
  const [type, setType] = useState<CardType>(card?.card_type ?? "basic");

  const canSubmit = front.trim() && (type === "cloze" || back.trim());

  return (
    <div className="ws-modal-backdrop" onClick={onClose}>
      <div className="ws-modal sum-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="ws-modal-head">
          <h2>{card ? "Edit card" : "New card"}</h2>
          <button className="ws-icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <div className="sum-modal-body">
          <label className="ws-field">
            <span>Type</span>
            <div className="fc-type-pills">
              {TYPES.map((t) => (
                <button key={t} type="button" className={`fc-type-pill${type === t ? " active" : ""}`} onClick={() => setType(t)}>
                  {CARD_TYPE_META[t].icon} {CARD_TYPE_META[t].label}
                </button>
              ))}
            </div>
          </label>
          <label className="ws-field">
            <span>{type === "cloze" ? "Text (use ____ for the blank)" : "Front (question / prompt)"}</span>
            <textarea rows={2} value={front} onChange={(e) => setFront(e.target.value)} autoFocus />
          </label>
          <label className="ws-field">
            <span>Back (answer){type === "cloze" && <em className="ws-field-opt"> (optional for cloze)</em>}</span>
            <textarea rows={3} value={back} onChange={(e) => setBack(e.target.value)} />
          </label>
          <label className="ws-field">
            <span>Hint <em className="ws-field-opt">(optional)</em></span>
            <input value={hint} onChange={(e) => setHint(e.target.value)} />
          </label>
          {error && <div className="ws-error-banner">{error}</div>}
        </div>
        <footer className="ws-modal-foot">
          <button className="ws-btn ghost" onClick={onClose} disabled={submitting}>Cancel</button>
          <button className="ws-btn primary" disabled={submitting || !canSubmit}
                  onClick={() => onSubmit({ front: front.trim(), back: back.trim(), hint: hint.trim(), card_type: type })}>
            {submitting ? "Saving…" : card ? "Save" : "Add card"}
          </button>
        </footer>
      </div>
    </div>
  );
}
