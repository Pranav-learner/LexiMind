// The "New note" modal. Two paths, one model:
//   • Blank    — create an empty note immediately and open the editor.
//   • AI Notes — pick a template + scope (whole workspace or one document) and generate.
// The document picker is fed by listDocuments (ready docs only). On submit it calls the parent's
// onBlank/onGenerate handlers; the parent owns the API calls + navigation.

import { useEffect, useMemo, useState } from "react";
import { listDocuments } from "../../api/documents";
import type { LibraryDocument, NoteGenerateInput, NoteType } from "../../types";
import { NOTE_TYPES, NOTE_TYPE_META } from "./constants";

type Tab = "blank" | "ai";
type Scope = "workspace" | "document";

interface Props {
  workspaceId: string;
  initialDocumentId?: string;
  submitting: boolean;
  serverError: string | null;
  onBlank: (title: string) => void;
  onGenerate: (payload: NoteGenerateInput) => void;
  onClose: () => void;
}

export default function NewNoteModal({
  workspaceId, initialDocumentId, submitting, serverError, onBlank, onGenerate, onClose,
}: Props) {
  const [tab, setTab] = useState<Tab>(initialDocumentId ? "ai" : "blank");
  const [title, setTitle] = useState("");
  const [noteType, setNoteType] = useState<NoteType>("study");
  const [scope, setScope] = useState<Scope>(initialDocumentId ? "document" : "workspace");
  const [docId, setDocId] = useState<string>(initialDocumentId || "");
  const [docs, setDocs] = useState<LibraryDocument[]>([]);

  useEffect(() => {
    let alive = true;
    listDocuments(workspaceId, { page_size: 100, sort_by: "updated_at", order: "desc" })
      .then((res) => alive && setDocs(res.items.filter((d) => d.processing_status === "ready")))
      .catch(() => {});
    return () => { alive = false; };
  }, [workspaceId]);

  const canGenerate = useMemo(
    () => scope === "workspace" || !!docId,
    [scope, docId],
  );

  function submit() {
    if (tab === "blank") {
      onBlank(title.trim());
      return;
    }
    const payload: NoteGenerateInput = { note_type: noteType, scope };
    if (scope === "document") payload.document_id = docId;
    if (title.trim()) payload.title = title.trim();
    onGenerate(payload);
  }

  return (
    <div className="ws-modal-backdrop" onClick={onClose}>
      <div className="ws-modal sum-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Create note">
        <header className="ws-modal-head">
          <h2>📝 New note</h2>
          <button className="ws-icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="ws-segment sum-scope-segment">
          <button className={tab === "blank" ? "active" : ""} onClick={() => setTab("blank")}>✏️ Blank note</button>
          <button className={tab === "ai" ? "active" : ""} onClick={() => setTab("ai")}>✨ AI notes</button>
        </div>

        <div className="sum-modal-body">
          <label className="ws-field">
            <span>Title {tab === "ai" && <em className="ws-field-opt">(optional)</em>}</span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={tab === "blank" ? "Untitled note" : "Auto-generated if left blank"}
              autoFocus
            />
          </label>

          {tab === "ai" && (
            <>
              <div className="ws-field">
                <span>Template</span>
                <div className="note-type-grid">
                  {NOTE_TYPES.map((t) => (
                    <button
                      key={t}
                      type="button"
                      className={`note-type-tile${noteType === t ? " active" : ""}`}
                      onClick={() => setNoteType(t)}
                    >
                      <span className="note-type-icon" aria-hidden="true">{NOTE_TYPE_META[t].icon}</span>
                      <span className="note-type-label">{NOTE_TYPE_META[t].label}</span>
                      <span className="note-type-blurb">{NOTE_TYPE_META[t].blurb}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="ws-segment sum-scope-segment">
                <button className={scope === "workspace" ? "active" : ""} onClick={() => setScope("workspace")}>
                  🗂 Whole workspace
                </button>
                <button className={scope === "document" ? "active" : ""} onClick={() => setScope("document")}>
                  📄 One document
                </button>
              </div>

              {scope === "document" && (
                <label className="ws-field">
                  <span>Document</span>
                  <select value={docId} onChange={(e) => setDocId(e.target.value)}>
                    <option value="">Select a document…</option>
                    {docs.map((d) => (
                      <option key={d.id} value={d.id}>{d.display_name || d.filename}</option>
                    ))}
                  </select>
                </label>
              )}
            </>
          )}

          {serverError && <div className="ws-error-banner">{serverError}</div>}
        </div>

        <footer className="ws-modal-foot">
          <button className="ws-btn ghost" onClick={onClose} disabled={submitting}>Cancel</button>
          <button
            className="ws-btn primary"
            onClick={submit}
            disabled={submitting || (tab === "ai" && !canGenerate)}
          >
            {submitting ? "Working…" : tab === "blank" ? "Create note" : "✨ Generate notes"}
          </button>
        </footer>
      </div>
    </div>
  );
}
