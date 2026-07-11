// The "New deck" modal. Two paths, one model:
//   • Empty deck — create a named deck to fill manually.
//   • AI deck    — pick scope (workspace or a document), card type, and count → generate.
// The document picker is fed by listDocuments (ready docs only).

import { useEffect, useMemo, useState } from "react";
import { listDocuments } from "../../api/documents";
import type { CardTypePref, DeckGenerateInput, LibraryDocument } from "../../types";
import { CARD_TYPE_PREFS } from "./constants";

type Tab = "empty" | "ai";
type Scope = "workspace" | "document";

interface Props {
  workspaceId: string;
  initialDocumentId?: string;
  submitting: boolean;
  serverError: string | null;
  onEmpty: (name: string) => void;
  onGenerate: (payload: DeckGenerateInput) => void;
  onClose: () => void;
}

export default function GenerateDeckModal({
  workspaceId, initialDocumentId, submitting, serverError, onEmpty, onGenerate, onClose,
}: Props) {
  const [tab, setTab] = useState<Tab>(initialDocumentId ? "ai" : "empty");
  const [name, setName] = useState("");
  const [scope, setScope] = useState<Scope>(initialDocumentId ? "document" : "workspace");
  const [docId, setDocId] = useState(initialDocumentId || "");
  const [pref, setPref] = useState<CardTypePref>("mixed");
  const [count, setCount] = useState(15);
  const [docs, setDocs] = useState<LibraryDocument[]>([]);

  useEffect(() => {
    let alive = true;
    listDocuments(workspaceId, { page_size: 100, sort_by: "updated_at", order: "desc" })
      .then((r) => alive && setDocs(r.items.filter((d) => d.processing_status === "ready")))
      .catch(() => {});
    return () => { alive = false; };
  }, [workspaceId]);

  const canGenerate = useMemo(() => scope === "workspace" || !!docId, [scope, docId]);

  function submit() {
    if (tab === "empty") { onEmpty(name.trim()); return; }
    const payload: DeckGenerateInput = { scope, card_type_pref: pref, count };
    if (scope === "document") payload.document_id = docId;
    if (name.trim()) payload.name = name.trim();
    onGenerate(payload);
  }

  return (
    <div className="ws-modal-backdrop" onClick={onClose}>
      <div className="ws-modal sum-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Create deck">
        <header className="ws-modal-head">
          <h2>🎴 New deck</h2>
          <button className="ws-icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="ws-segment sum-scope-segment">
          <button className={tab === "empty" ? "active" : ""} onClick={() => setTab("empty")}>📇 Empty deck</button>
          <button className={tab === "ai" ? "active" : ""} onClick={() => setTab("ai")}>✨ AI flashcards</button>
        </div>

        <div className="sum-modal-body">
          <label className="ws-field">
            <span>Deck name {tab === "ai" && <em className="ws-field-opt">(optional)</em>}</span>
            <input value={name} onChange={(e) => setName(e.target.value)}
                   placeholder={tab === "empty" ? "e.g. Operating Systems" : "Auto-named if left blank"} autoFocus />
          </label>

          {tab === "ai" && (
            <>
              <div className="ws-segment sum-scope-segment">
                <button className={scope === "workspace" ? "active" : ""} onClick={() => setScope("workspace")}>🗂 Whole workspace</button>
                <button className={scope === "document" ? "active" : ""} onClick={() => setScope("document")}>📄 One document</button>
              </div>

              {scope === "document" && (
                <label className="ws-field">
                  <span>Document</span>
                  <select value={docId} onChange={(e) => setDocId(e.target.value)}>
                    <option value="">Select a document…</option>
                    {docs.map((d) => <option key={d.id} value={d.id}>{d.display_name || d.filename}</option>)}
                  </select>
                </label>
              )}

              <div className="ws-field">
                <span>Card type</span>
                <div className="fc-type-grid">
                  {CARD_TYPE_PREFS.map((t) => (
                    <button key={t.value} type="button"
                            className={`note-type-tile${pref === t.value ? " active" : ""}`}
                            onClick={() => setPref(t.value)}>
                      <span className="note-type-label">{t.label}</span>
                      <span className="note-type-blurb">{t.blurb}</span>
                    </button>
                  ))}
                </div>
              </div>

              <label className="ws-field">
                <span>Number of cards: <strong>{count}</strong></span>
                <input type="range" min={5} max={40} step={5} value={count}
                       onChange={(e) => setCount(Number(e.target.value))} />
              </label>
            </>
          )}

          {serverError && <div className="ws-error-banner">{serverError}</div>}
        </div>

        <footer className="ws-modal-foot">
          <button className="ws-btn ghost" onClick={onClose} disabled={submitting}>Cancel</button>
          <button className="ws-btn primary" onClick={submit} disabled={submitting || (tab === "ai" && !canGenerate)}>
            {submitting ? "Working…" : tab === "empty" ? "Create deck" : "✨ Generate"}
          </button>
        </footer>
      </div>
    </div>
  );
}
