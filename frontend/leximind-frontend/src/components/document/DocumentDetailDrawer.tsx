// Right-side slide-in drawer showing a document's full detail. Fetches getDocument on open
// (for the index_health block), supports inline edit of display_name / description via PATCH,
// and exposes Rename / Archive / Restore / Reindex / Delete actions. Closes on Escape or
// overlay click.

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../../api/documents";
import { ApiError } from "../../api/client";
import type { LibraryDocument, LibraryDocumentDetail } from "../../types";
import { fileIcon, humanSize, relativeTime } from "./constants";
import ProcessingPanel from "./ProcessingPanel";
import VisionPanel from "./VisionPanel";

interface Props {
  workspaceId: string;
  doc: LibraryDocument;
  onClose: () => void;
  // Called after any mutation so the parent list refetches. Receives the updated doc when
  // available (null after a delete).
  onChanged: (doc: LibraryDocument | null) => void;
}

export default function DocumentDetailDrawer({
  workspaceId,
  doc,
  onClose,
  onChanged,
}: Props) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<LibraryDocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [editName, setEditName] = useState(false);
  const [name, setName] = useState(doc.display_name || doc.filename);
  const [editDesc, setEditDesc] = useState(false);
  const [desc, setDesc] = useState(doc.description || "");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api.getDocument(workspaceId, doc.id);
      setDetail(d);
      setName(d.display_name || d.filename);
      setDesc(d.description || "");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load document.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, doc.id]);

  useEffect(() => {
    load();
  }, [load]);

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const d = detail ?? doc;

  async function mutate(fn: () => Promise<LibraryDocument | void>, refetch = true) {
    setBusy(true);
    setError(null);
    try {
      const updated = await fn();
      if (updated) {
        setDetail((prev) => (prev ? { ...prev, ...updated } : prev));
        onChanged(updated);
        if (refetch) await load();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveName() {
    const trimmed = name.trim();
    if (!trimmed) return;
    await mutate(() => api.updateDocument(workspaceId, doc.id, { display_name: trimmed }), false);
    setEditName(false);
  }

  async function saveDesc() {
    await mutate(() => api.updateDocument(workspaceId, doc.id, { description: desc.trim() }), false);
    setEditDesc(false);
  }

  async function handleDelete() {
    const permanent = window.confirm(
      "Delete this document?\n\nOK = permanent delete (cannot be undone).\nCancel = soft delete (moved to trash).",
    );
    // window.confirm only gives yes/no; use a second confirm to guard permanent deletes.
    if (permanent) {
      if (!window.confirm("Confirm PERMANENT delete? This cannot be undone.")) return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.deleteDocument(workspaceId, doc.id, permanent);
      onChanged(null);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed.");
      setBusy(false);
    }
  }

  return (
    <div className="doc-drawer-overlay" onMouseDown={onClose}>
      <aside
        className="doc-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Document details"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="doc-drawer-header">
          <div className="doc-drawer-title">
            <span className="ws-card-icon doc-card-icon">{fileIcon(d.file_type, d.media_type)}</span>
            <div>
              {editName ? (
                <div className="doc-inline-edit">
                  <input
                    autoFocus
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && saveName()}
                  />
                  <button className="ws-btn primary" onClick={saveName} disabled={busy}>Save</button>
                  <button className="ws-btn ghost" onClick={() => { setEditName(false); setName(d.display_name || d.filename); }}>Cancel</button>
                </div>
              ) : (
                <h2>
                  {d.display_name || d.filename}
                  <button className="ws-icon-btn" title="Rename" aria-label="Rename" onClick={() => setEditName(true)}>✏️</button>
                </h2>
              )}
              <span className="doc-drawer-filename">{d.filename}</span>
            </div>
          </div>
          <button className="ws-icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {error && <div className="ws-error-banner">{error}</div>}

        <div className="doc-drawer-actions">
          <button className="ws-btn primary" onClick={() => navigate(`/workspace/${workspaceId}/document/${doc.id}`)}>📖 Open in viewer</button>
          <button className="ws-btn ghost" disabled={busy} onClick={() => mutate(() => api.reindexDocument(workspaceId, doc.id))}>🔄 Reindex</button>
          {d.is_archived ? (
            <button className="ws-btn ghost" disabled={busy} onClick={() => mutate(() => api.restoreDocument(workspaceId, doc.id))}>♻️ Restore</button>
          ) : (
            <button className="ws-btn ghost" disabled={busy} onClick={() => mutate(() => api.archiveDocument(workspaceId, doc.id))}>📥 Archive</button>
          )}
          <button className="ws-btn ghost doc-danger-btn" disabled={busy} onClick={handleDelete}>🗑️ Delete</button>
        </div>

        <div className="doc-drawer-body">
          {loading && <p className="doc-muted">Loading…</p>}

          <Section title="General">
            <Field label="Display name" value={d.display_name || d.filename} />
            <Field label="Filename" value={d.filename} />
            <div className="doc-field">
              <span className="doc-field-label">Description</span>
              {editDesc ? (
                <div className="doc-inline-edit column">
                  <textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} />
                  <div className="doc-inline-actions">
                    <button className="ws-btn primary" onClick={saveDesc} disabled={busy}>Save</button>
                    <button className="ws-btn ghost" onClick={() => { setEditDesc(false); setDesc(d.description || ""); }}>Cancel</button>
                  </div>
                </div>
              ) : (
                <span className="doc-field-value">
                  {d.description || <em className="doc-muted">No description</em>}
                  <button className="ws-icon-btn" title="Edit description" aria-label="Edit description" onClick={() => setEditDesc(true)}>✏️</button>
                </span>
              )}
            </div>
            <Field label="File type" value={d.file_type.toUpperCase()} />
            <Field label="Size" value={humanSize(d.file_size)} />
            <Field label="Language" value={d.language || "—"} />
          </Section>

          <Section title="Processing">
            <Field label="Status" value={d.processing_status} />
            <Field label="Stage" value={d.processing_stage.replace(/_/g, " ")} />
            <Field label="Duration" value={d.processing_ms != null ? `${d.processing_ms} ms` : "—"} />
            <Field label="Progress" value={`${d.upload_progress}%`} />
            {d.processing_error && <Field label="Error" value={d.processing_error} danger />}
          </Section>

          <Section title="Index">
            <Field label="Indexing status" value={d.indexing_status} />
            {detail?.index_health ? (
              <>
                <Field label="Chunks" value={String(detail.index_health.chunk_count)} />
                <Field label="Embeddings" value={String(detail.index_health.embedding_count)} />
                <Field label="FAISS" value={detail.index_health.faiss_status} />
                <Field label="BM25" value={detail.index_health.bm25_status} />
                <Field label="Health" value={detail.index_health.index_health} />
              </>
            ) : (
              !loading && <span className="doc-muted">No index health data.</span>
            )}
          </Section>

          <Section title="Embedding">
            <Field label="Model" value={d.embedding_model || "—"} />
            <Field label="Dimension" value={d.embedding_dimension ? String(d.embedding_dimension) : "—"} />
          </Section>

          <Section title="Chunk statistics">
            <Field label="Chunks" value={String(d.chunk_count)} />
            <Field label="Pages" value={String(d.page_count)} />
            <Field label="Words" value={String(d.word_count)} />
          </Section>

          <Section title="Storage">
            <Field label="Size" value={humanSize(d.file_size)} />
            <Field label="MIME type" value={d.mime_type || "—"} />
          </Section>

          <Section title="Workspace">
            <Field label="Workspace ID" value={d.workspace_id} />
          </Section>

          <Section title="Recent activity">
            <Field label="Created" value={relativeTime(d.created_at)} />
            <Field label="Updated" value={relativeTime(d.updated_at)} />
            <Field label="Last indexed" value={relativeTime(d.last_indexed_at)} />
          </Section>

          <Section title="AI features">
            <div className="doc-ai-features">
              <button
                className="ws-btn ghost"
                title="Summarize this document"
                onClick={() =>
                  navigate(`/workspace/${workspaceId}/summaries`, {
                    state: { summarize: { document_id: doc.id } },
                  })
                }
              >
                ✨ Summarize
              </button>
              <button className="ws-btn ghost" disabled title="Coming soon">💬 Chat</button>
              <button className="ws-btn ghost" disabled title="Coming soon">🎴 Flashcards</button>
            </div>
          </Section>

          <Section title="Multimodal processing">
            <ProcessingPanel workspaceId={workspaceId} documentId={doc.id} />
          </Section>

          <Section title="Vision intelligence">
            <VisionPanel workspaceId={workspaceId} documentId={doc.id} />
          </Section>
        </div>
      </aside>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="doc-section">
      <h3 className="doc-section-title">{title}</h3>
      <div className="doc-section-body">{children}</div>
    </section>
  );
}

function Field({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="doc-field">
      <span className="doc-field-label">{label}</span>
      <span className={`doc-field-value ${danger ? "danger" : ""}`}>{value}</span>
    </div>
  );
}
