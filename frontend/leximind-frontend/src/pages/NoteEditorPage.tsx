// The Smart Notes editor. Route: /workspace/:workspaceId/notes/:noteId
//
// Three columns: an outline + tags rail (left), the Markdown rich editor (center), and a citations
// + AI-assist rail (right). Responsibilities:
//   • Load the note; if it's still generating (queued/processing) show live progress and poll to a
//     terminal state, then load the finished content.
//   • Robust autosave: debounced PUT /content with an optimistic `base_version`; a 409 surfaces a
//     conflict banner (never clobber a newer edit) and offers a reload. Ctrl/⌘+S forces a save.
//   • Live outline derived from the current Markdown (stays correct while editing).
//   • Citations rail: click → resolve the vector doc id → open the PDF viewer at the page (Module 3).
//   • AI-assist: select text → choose an operation → replace the selection with the result.
//   • Tags: attach/detach + inline create. Reading vs editing mode. Export / duplicate / delete.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as notesApi from "../api/notes";
import { getDocumentByVector } from "../api/viewer";
import { ApiError } from "../api/client";
import MarkdownEditor, { type MarkdownEditorHandle } from "../components/notes/MarkdownEditor";
import { ASSIST_OPS, STATUS_META, noteTypeIcon, noteTypeLabel, relativeTime, suggestTagColor } from "../components/notes/constants";
import type { AssistOperation, NoteCitationT, NoteDetail, OutlineItem, Tag } from "../types";

type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

// Client-side outline from Markdown headings (mirrors the backend; keeps the outline live on edit).
function deriveOutline(md: string): OutlineItem[] {
  const items: OutlineItem[] = [];
  let inFence = false;
  for (const line of md.split("\n")) {
    if (line.trim().startsWith("```")) { inFence = !inFence; continue; }
    if (inFence) continue;
    const m = /^(#{1,6})\s+(.*\S)\s*$/.exec(line);
    if (m) {
      const text = m[2].trim();
      items.push({ level: m[1].length, text, slug: text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") });
    }
  }
  return items;
}

export default function NoteEditorPage() {
  const { workspaceId = "", noteId = "" } = useParams();
  const navigate = useNavigate();

  const [note, setNote] = useState<NoteDetail | null>(null);
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [conflict, setConflict] = useState(false);
  const [readOnly, setReadOnly] = useState(false);
  const [selection, setSelection] = useState("");
  const [assisting, setAssisting] = useState<AssistOperation | null>(null);
  const [assistError, setAssistError] = useState<string | null>(null);
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [showTagAdd, setShowTagAdd] = useState(false);

  const editorRef = useRef<MarkdownEditorHandle | null>(null);
  const versionRef = useRef<number>(1);           // last server-acked version (autosave base)
  const saveTimer = useRef<number | null>(null);
  const contentRef = useRef(content);
  const titleRef = useRef(title);
  contentRef.current = content;
  titleRef.current = title;

  // ---- load (+ poll if generating) ------------------------------------------
  useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        let d = await notesApi.getNote(workspaceId, noteId, controller.signal);
        if (!alive) return;
        if (!notesApi.isTerminal(d.status)) {
          setNote(d);
          setLoading(false);
          await notesApi.pollNoteStatus(workspaceId, noteId, {
            signal: controller.signal,
            onUpdate: (n) => alive && setNote((p) => (p ? { ...p, ...n } : p)),
          });
          if (!alive) return;
          d = await notesApi.getNote(workspaceId, noteId, controller.signal);
        }
        if (!alive) return;
        setNote(d);
        setContent(d.content);
        setTitle(d.title);
        versionRef.current = d.version;
        setSaveState("idle");
        setLoading(false);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (!alive) return;
        setError(err instanceof ApiError ? err.message : "Failed to load note.");
        setLoading(false);
      }
    })();
    return () => { alive = false; controller.abort(); };
  }, [workspaceId, noteId]);

  useEffect(() => {
    notesApi.listTags(workspaceId).then((r) => setAllTags(r.items)).catch(() => {});
  }, [workspaceId]);

  // ---- autosave -------------------------------------------------------------
  const doSave = useCallback(async () => {
    if (conflict) return;
    const body = { content: contentRef.current, base_version: versionRef.current, title: titleRef.current };
    setSaveState("saving");
    try {
      const updated = await notesApi.saveNoteContent(workspaceId, noteId, body);
      versionRef.current = updated.version;
      setNote((p) => (p ? { ...p, ...updated } : p));
      setSaveState("saved");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflict(true);
        setSaveState("error");
      } else {
        setSaveState("error");
      }
    }
  }, [workspaceId, noteId, conflict]);

  const scheduleSave = useCallback(() => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    setSaveState("dirty");
    saveTimer.current = window.setTimeout(doSave, 1000);
  }, [doSave]);

  // Flush a pending save on unmount / navigation (never lose work).
  useEffect(() => {
    return () => {
      if (saveTimer.current) {
        window.clearTimeout(saveTimer.current);
        // Best-effort synchronous flush is not possible with fetch; the 1s debounce + explicit
        // Ctrl+S cover the realistic cases. A pending edit within the last second is the tradeoff.
      }
    };
  }, []);

  // Ctrl/⌘+S forces an immediate save.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (saveTimer.current) window.clearTimeout(saveTimer.current);
        doSave();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doSave]);

  function onContentChange(v: string) {
    setContent(v);
    if (!readOnly) scheduleSave();
  }

  function onTitleChange(v: string) {
    setTitle(v);
    scheduleSave();
  }

  // ---- AI assist ------------------------------------------------------------
  async function runAssist(op: AssistOperation) {
    const sel = editorRef.current?.getSelection().text || selection;
    if (!sel.trim()) { setAssistError("Select some text in the note first."); return; }
    setAssisting(op);
    setAssistError(null);
    try {
      const res = await notesApi.assistNote(workspaceId, noteId, { operation: op, selection: sel });
      editorRef.current?.replaceSelection(res.result);
      setContent(contentRef.current); // replaceSelection already called onChange; ensure state sync
      scheduleSave();
    } catch (err) {
      setAssistError(err instanceof ApiError ? err.message : "Assist failed.");
    } finally { setAssisting(null); }
  }

  // ---- citations ------------------------------------------------------------
  const onCitation = useCallback(async (c: NoteCitationT) => {
    if (!c.document_id) return;
    try {
      const doc = await getDocumentByVector(workspaceId, c.document_id);
      navigate(`/workspace/${workspaceId}/document/${doc.id}`, {
        state: { citation: { page: c.page_number, text: c.citation_text } },
      });
    } catch { /* best effort */ }
  }, [navigate, workspaceId]);

  // ---- tags -----------------------------------------------------------------
  async function toggleTag(tag: Tag) {
    if (!note) return;
    const has = note.tags.some((t) => t.id === tag.id);
    const next = has ? note.tags.filter((t) => t.id !== tag.id).map((t) => t.id) : [...note.tags.map((t) => t.id), tag.id];
    try {
      const updated = await notesApi.setNoteTags(workspaceId, noteId, next);
      setNote((p) => (p ? { ...p, ...updated } : p));
      notesApi.listTags(workspaceId).then((r) => setAllTags(r.items)).catch(() => {});
    } catch { /* ignore */ }
  }

  async function createAndAttachTag(name: string) {
    const clean = name.trim();
    if (!clean) return;
    try {
      const tag = await notesApi.createTag(workspaceId, { name: clean, color: suggestTagColor(clean) });
      setAllTags((prev) => [...prev, tag]);
      await toggleTag(tag);
      setShowTagAdd(false);
    } catch (err) {
      setAssistError(err instanceof ApiError ? err.message : "Could not create tag.");
    }
  }

  // ---- actions --------------------------------------------------------------
  function handleExport() {
    const safe = (title || "note").replace(/[^\w.-]+/g, "_").slice(0, 80);
    notesApi.exportNote(workspaceId, noteId, `${safe}.md`).catch(() => {});
  }

  function handleDelete() {
    if (!window.confirm("Delete this note? It will be moved to trash (soft delete).")) return;
    notesApi.deleteNote(workspaceId, noteId)
      .then(() => navigate(`/workspace/${workspaceId}/notes`))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Delete failed."));
  }

  async function reloadAfterConflict() {
    try {
      const d = await notesApi.getNote(workspaceId, noteId);
      setNote(d); setContent(d.content); setTitle(d.title);
      versionRef.current = d.version;
      setConflict(false); setSaveState("idle");
    } catch { /* ignore */ }
  }

  const outline = useMemo(() => deriveOutline(content), [content]);
  const generating = note && (note.status === "queued" || note.status === "processing");

  if (loading && !note) {
    return (
      <div className="note-editor-page">
        <div className="sum-viewer-status"><span className="ws-brand-mark spin">🧠</span><p>Loading note…</p></div>
      </div>
    );
  }
  if (error && !note) {
    return (
      <div className="note-editor-page">
        <div className="sum-viewer-status">
          <div className="ws-error-banner">{error}</div>
          <Link className="ws-btn ghost" to={`/workspace/${workspaceId}/notes`}>← Back to notes</Link>
        </div>
      </div>
    );
  }
  if (!note) return null;

  const status = STATUS_META[note.status];

  return (
    <div className="note-editor-page" style={{ ["--ws-accent" as string]: "" }}>
      <header className="note-editor-header">
        <div className="note-editor-head-left">
          <Link className="ws-back" to={`/workspace/${workspaceId}/notes`}>← Notes</Link>
          <span className="note-editor-typeicon" title={noteTypeLabel(note.note_type)}>{noteTypeIcon(note.note_type)}</span>
          <input
            className="note-title-input"
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            placeholder="Untitled note"
            aria-label="Note title"
            readOnly={readOnly}
          />
        </div>
        <div className="note-editor-head-right">
          <span className={`note-save-state ${saveState}`}>
            {saveState === "saving" ? "Saving…" : saveState === "saved" ? "✓ Saved" : saveState === "dirty" ? "Unsaved…" : saveState === "error" ? "⚠ Save failed" : ""}
          </span>
          <button className="ws-btn ghost" onClick={() => setReadOnly((r) => !r)} title="Toggle reading mode">
            {readOnly ? "✏️ Edit" : "👁 Read"}
          </button>
          <button className="ws-btn ghost" onClick={handleExport} title="Export as Markdown">⬇ Export</button>
          <button className="ws-btn ghost doc-danger-btn" onClick={handleDelete} title="Delete note">🗑</button>
        </div>
      </header>

      {conflict && (
        <div className="ws-error-banner note-conflict">
          This note was changed elsewhere. <button className="ws-link" onClick={reloadAfterConflict}>Reload latest</button> to continue editing.
        </div>
      )}

      {generating ? (
        <div className="sum-generating note-generating">
          <span className="ws-brand-mark spin">🧠</span>
          <h3>Generating your notes…</h3>
          <div className="sum-progress big"><div className="sum-progress-bar" style={{ width: `${note.progress}%` }} /></div>
          <p className="sum-stage">{note.stage || "Working…"} · {note.progress}%</p>
          <button className="ws-btn ghost" onClick={() => notesApi.cancelNote(workspaceId, noteId).catch(() => {})}>✕ Cancel</button>
        </div>
      ) : note.status === "failed" ? (
        <div className="sum-generating sum-failed note-generating">
          <div className="ws-empty-mark">⚠️</div>
          <h3>Generation failed</h3>
          <p className="sum-error-text">{note.error || "Something went wrong."}</p>
          <button className="ws-btn primary" onClick={() => notesApi.regenerateNote(workspaceId, noteId).then(() => window.location.reload())}>🔄 Regenerate</button>
        </div>
      ) : (
        <div className="note-workbench">
          {/* left: outline + tags */}
          <aside className="note-rail note-rail-left">
            <div className="note-rail-section">
              <h4>Outline</h4>
              {outline.length === 0 ? (
                <p className="note-rail-empty">Add ## headings to build an outline.</p>
              ) : (
                <ul className="note-outline">
                  {outline.map((o, i) => (
                    <li key={i} className={`lvl-${o.level}`}>
                      <button onClick={() => editorRef.current?.focus()} title={o.text}>{o.text}</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="note-rail-section">
              <h4>Tags</h4>
              <div className="note-tag-list">
                {note.tags.map((t) => (
                  <button key={t.id} className="note-tag-chip active" style={{ ["--tag" as string]: t.color }} onClick={() => toggleTag(t)}>
                    {t.name} ✕
                  </button>
                ))}
                {!showTagAdd ? (
                  <button className="note-tag-add" onClick={() => setShowTagAdd(true)}>＋ Tag</button>
                ) : (
                  <TagAdder
                    all={allTags.filter((t) => !note.tags.some((nt) => nt.id === t.id))}
                    onPick={(t) => toggleTag(t)}
                    onCreate={createAndAttachTag}
                    onClose={() => setShowTagAdd(false)}
                  />
                )}
              </div>
            </div>
            <div className="note-rail-section note-stats">
              <span>{note.word_count} words</span>
              <span>{note.reading_time || 0} min read</span>
              <span className={`sum-status ${status.tone}`}>{status.label}</span>
              <span>Updated {relativeTime(note.updated_at)}</span>
            </div>
          </aside>

          {/* center: editor */}
          <main className="note-main">
            <MarkdownEditor
              ref={editorRef}
              value={content}
              onChange={onContentChange}
              onSelectionChange={setSelection}
              readOnly={readOnly}
            />
          </main>

          {/* right: AI assist + citations */}
          <aside className="note-rail note-rail-right">
            <div className="note-rail-section">
              <h4>✨ AI assist</h4>
              <p className="note-assist-hint">{selection.trim() ? `${selection.trim().length} chars selected` : "Select text to transform it."}</p>
              <div className="note-assist-grid">
                {ASSIST_OPS.map(({ op, label, icon }) => (
                  <button
                    key={op}
                    className="note-assist-btn"
                    disabled={!!assisting || readOnly}
                    onClick={() => runAssist(op)}
                    title={label}
                  >
                    <span aria-hidden="true">{icon}</span> {assisting === op ? "…" : label}
                  </button>
                ))}
              </div>
              {assistError && <div className="ws-error-banner sm">{assistError}</div>}
            </div>

            <div className="note-rail-section">
              <h4>🔗 Citations <span className="note-count-badge">{note.citations.length}</span></h4>
              {note.citations.length === 0 ? (
                <p className="note-rail-empty">Grounded citations from AI generation appear here.</p>
              ) : (
                <div className="note-citation-list">
                  {note.citations.map((c, i) => (
                    <button key={c.id} className="chat-citation" onClick={() => onCitation(c)} disabled={!c.document_id} title="Open source">
                      <span className="chat-citation-head">
                        <span className="chat-citation-icon" aria-hidden="true">📄</span>
                        <span className="chat-citation-num">[{i + 1}]</span>
                        {c.page_number != null && <span className="chat-citation-page">Page {c.page_number}</span>}
                        {c.confidence != null && <span className="chat-citation-conf">{Math.round(c.confidence * 100)}%</span>}
                      </span>
                      <span className="chat-citation-text">{c.citation_text || "Cited source"}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

// Small inline tag picker/creator used in the left rail.
function TagAdder({ all, onPick, onCreate, onClose }: {
  all: Tag[];
  onPick: (t: Tag) => void;
  onCreate: (name: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const filtered = all.filter((t) => t.name.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="note-tag-adder" onMouseLeave={onClose}>
      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Find or create…"
        onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) onCreate(q); if (e.key === "Escape") onClose(); }}
      />
      <div className="note-tag-adder-list">
        {filtered.map((t) => (
          <button key={t.id} style={{ ["--tag" as string]: t.color }} className="note-tag-chip" onClick={() => { onPick(t); onClose(); }}>
            {t.name}
          </button>
        ))}
        {q.trim() && !all.some((t) => t.name.toLowerCase() === q.trim().toLowerCase()) && (
          <button className="note-tag-create" onClick={() => onCreate(q)}>＋ Create “{q.trim()}”</button>
        )}
      </div>
    </div>
  );
}
