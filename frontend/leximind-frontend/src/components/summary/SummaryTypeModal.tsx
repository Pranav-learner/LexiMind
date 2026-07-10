// The "New summary" dialog. Step 1: pick a summary type (cards from SUMMARY_TYPES). Step 2: pick
// a scope — the whole workspace, or a set of selected documents (a searchable multi-select fed by
// listDocuments). Plus an optional title. On Generate it builds the create payload (inferring
// scope: one doc → `document`, many → `multi`, none → `workspace`) and hands it upward. Closes on
// Escape or overlay click.

import { useCallback, useEffect, useRef, useState } from "react";
import { listDocuments } from "../../api/documents";
import type { LibraryDocument, SummaryCreateInput, SummaryType } from "../../types";
import { SUMMARY_TYPES } from "./constants";

type ScopeChoice = "workspace" | "documents";

interface Props {
  workspaceId: string;
  initialType?: SummaryType;
  initialScope?: ScopeChoice;
  initialDocumentIds?: string[];
  submitting?: boolean;
  serverError?: string | null;
  onSubmit: (payload: SummaryCreateInput) => void;
  onClose: () => void;
}

export default function SummaryTypeModal({
  workspaceId,
  initialType = "standard",
  initialScope = "workspace",
  initialDocumentIds = [],
  submitting,
  serverError,
  onSubmit,
  onClose,
}: Props) {
  const [type, setType] = useState<SummaryType>(initialType);
  const [scope, setScope] = useState<ScopeChoice>(initialScope);
  const [title, setTitle] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set(initialDocumentIds));

  const [docs, setDocs] = useState<LibraryDocument[]>([]);
  const [docSearch, setDocSearch] = useState("");
  const [loadingDocs, setLoadingDocs] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Fetch the document picker list (only while the "documents" scope is chosen), debounced.
  const loadDocs = useCallback(
    async (search: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoadingDocs(true);
      try {
        const res = await listDocuments(
          workspaceId,
          { page: 1, page_size: 50, search, archived: "active", indexed: "indexed", sort_by: "updated_at", order: "desc" },
          controller.signal,
        );
        setDocs(res.items);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setDocs([]);
      } finally {
        setLoadingDocs(false);
      }
    },
    [workspaceId],
  );

  useEffect(() => {
    if (scope !== "documents") return;
    const t = setTimeout(() => loadDocs(docSearch), 250);
    return () => clearTimeout(t);
  }, [scope, docSearch, loadDocs]);

  useEffect(() => () => abortRef.current?.abort(), []);

  function toggleDoc(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const ids = Array.from(selected);
  const canSubmit = scope === "workspace" || ids.length > 0;

  function submit() {
    if (!canSubmit || submitting) return;
    const trimmedTitle = title.trim();
    const payload: SummaryCreateInput = { summary_type: type };
    if (trimmedTitle) payload.title = trimmedTitle;
    if (scope === "workspace") {
      payload.scope = "workspace";
    } else if (ids.length === 1) {
      payload.scope = "document";
      payload.document_id = ids[0];
    } else {
      payload.scope = "multi";
      payload.document_ids = ids;
    }
    onSubmit(payload);
  }

  return (
    <div className="ws-modal-overlay" onMouseDown={onClose}>
      <div
        className="ws-modal sum-modal"
        role="dialog"
        aria-modal="true"
        aria-label="New summary"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="ws-modal-header">
          <h2>New summary</h2>
          <button className="ws-icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="sum-modal-body">
          <div className="sum-field">
            <span className="sum-field-label">Summary type</span>
            <div className="sum-type-grid">
              {SUMMARY_TYPES.map((t) => (
                <button
                  type="button"
                  key={t.key}
                  className={`sum-type-option${type === t.key ? " selected" : ""}`}
                  onClick={() => setType(t.key)}
                  aria-pressed={type === t.key}
                >
                  <span className="sum-type-icon" aria-hidden="true">{t.icon}</span>
                  <span className="sum-type-name">{t.label}</span>
                  <span className="sum-type-desc">{t.description}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="sum-field">
            <span className="sum-field-label">Source</span>
            <div className="ws-segment sum-scope-segment">
              <button
                type="button"
                className={scope === "workspace" ? "active" : ""}
                onClick={() => setScope("workspace")}
              >
                🗂️ Whole workspace
              </button>
              <button
                type="button"
                className={scope === "documents" ? "active" : ""}
                onClick={() => setScope("documents")}
              >
                📄 Selected documents
              </button>
            </div>
          </div>

          {scope === "documents" && (
            <div className="sum-field">
              <input
                className="ws-search sum-doc-search"
                type="search"
                placeholder="Search documents to include…"
                value={docSearch}
                onChange={(e) => setDocSearch(e.target.value)}
              />
              <div className="sum-doc-list">
                {loadingDocs ? (
                  <p className="sum-muted">Loading documents…</p>
                ) : docs.length === 0 ? (
                  <p className="sum-muted">No indexed documents found.</p>
                ) : (
                  docs.map((d) => (
                    <label key={d.id} className={`sum-doc-item${selected.has(d.id) ? " selected" : ""}`}>
                      <input
                        type="checkbox"
                        checked={selected.has(d.id)}
                        onChange={() => toggleDoc(d.id)}
                      />
                      <span className="sum-doc-name">{d.display_name || d.filename}</span>
                      <span className="sum-doc-meta">{d.page_count} pg</span>
                    </label>
                  ))
                )}
              </div>
              <span className="sum-muted">{ids.length} selected</span>
            </div>
          )}

          <label className="sum-field">
            <span className="sum-field-label">Title <em>(optional)</em></span>
            <input
              className="sum-title-input"
              value={title}
              maxLength={200}
              placeholder="Auto-generated if left blank"
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>

          {serverError && <div className="ws-error-banner">{serverError}</div>}
        </div>

        <div className="ws-modal-actions">
          <button type="button" className="ws-btn ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button
            type="button"
            className="ws-btn primary"
            onClick={submit}
            disabled={submitting || !canSubmit}
          >
            {submitting ? "Generating…" : "✨ Generate"}
          </button>
        </div>
      </div>
    </div>
  );
}
