// The Smart Notes dashboard. Route: /workspace/:workspaceId/notes
//
// A toolbar + tag rail + paginated grid of NoteCard, plus a "New note" button (opens NewNoteModal:
// blank → create+open editor; AI → generate+open editor showing live progress). Opening a card
// navigates to the editor page (/notes/:noteId). Owns all query state: debounced search, type /
// pinned / archived filters, tag filter, sort, pagination. Each list fetch is guarded by an
// AbortController so a newer query aborts the older in-flight request. Honors a "make notes from
// this" hand-off (document/summary/chat) via router state.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import * as notesApi from "../api/notes";
import { getWorkspace } from "../api/workspaces";
import { ApiError } from "../api/client";
import NoteCard from "../components/notes/NoteCard";
import NotesToolbar from "../components/notes/NotesToolbar";
import NewNoteModal from "../components/notes/NewNoteModal";
import type {
  Note,
  NoteArchivedFilter,
  NoteGenerateInput,
  NotePinnedFilter,
  NoteSortField,
  NoteType,
  SortOrder,
  Tag,
  Workspace,
} from "../types";

const PAGE_SIZE = 12;

interface PresetState {
  makeNotes?: { document_id?: string; summary_id?: string; message_id?: string };
}

export default function NotesDashboard() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [items, setItems] = useState<Note[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [type, setType] = useState<NoteType | "">("");
  const [pinned, setPinned] = useState<NotePinnedFilter>("any");
  const [archived, setArchived] = useState<NoteArchivedFilter>("active");
  const [tagId, setTagId] = useState<string>("");
  const [sortBy, setSortBy] = useState<NoteSortField>("updated_at");
  const [order, setOrder] = useState<SortOrder>("desc");

  const [showModal, setShowModal] = useState(false);
  const [presetDocId, setPresetDocId] = useState<string | undefined>();
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const openNote = useCallback((id: string) => navigate(`/workspace/${workspaceId}/notes/${id}`), [navigate, workspaceId]);

  useEffect(() => {
    let alive = true;
    getWorkspace(workspaceId).then((w) => alive && setWorkspace(w)).catch(() => {});
    notesApi.listTags(workspaceId).then((r) => alive && setTags(r.items)).catch(() => {});
    return () => { alive = false; };
  }, [workspaceId]);

  // Handle a hand-off from the Library / Summaries / Chat ("make notes from this").
  useEffect(() => {
    const preset = (location.state as PresetState | null)?.makeNotes;
    if (!preset) return;
    navigate(location.pathname, { replace: true, state: null });
    (async () => {
      try {
        if (preset.summary_id) {
          const n = await notesApi.noteFromSummary(workspaceId, preset.summary_id);
          openNote(n.id);
        } else if (preset.message_id) {
          const n = await notesApi.noteFromMessage(workspaceId, preset.message_id);
          openNote(n.id);
        } else if (preset.document_id) {
          setPresetDocId(preset.document_id);
          setShowModal(true);
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Could not create note.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const res = await notesApi.listNotes(
        workspaceId,
        { page, page_size: PAGE_SIZE, search, note_type: type || undefined, pinned, archived,
          tag_id: tagId || undefined, sort_by: sortBy, order },
        controller.signal,
      );
      setItems(res.items);
      setTotal(res.total);
      setPages(res.pages);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Failed to load notes.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, page, search, type, pinned, archived, tagId, sortBy, order]);

  useEffect(() => { load(); return () => abortRef.current?.abort(); }, [load]);

  const refreshTags = useCallback(() => {
    notesApi.listTags(workspaceId).then((r) => setTags(r.items)).catch(() => {});
  }, [workspaceId]);

  async function mutate(fn: () => Promise<unknown>) {
    try { await fn(); await load(); refreshTags(); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Action failed."); }
  }

  function confirmDelete(n: Note) {
    if (window.confirm(`Delete "${n.title || "Untitled note"}"? It will be moved to trash (soft delete).`)) {
      mutate(() => notesApi.deleteNote(workspaceId, n.id));
    }
  }

  async function handleBlank(title: string) {
    setCreating(true);
    setCreateError(null);
    try {
      const n = await notesApi.createNote(workspaceId, { title: title || undefined, source: "blank" });
      setShowModal(false);
      openNote(n.id);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Failed to create note.");
    } finally { setCreating(false); }
  }

  async function handleGenerate(payload: NoteGenerateInput) {
    setCreating(true);
    setCreateError(null);
    try {
      const n = await notesApi.generateNote(workspaceId, payload);
      setShowModal(false);
      setPresetDocId(undefined);
      openNote(n.id); // editor shows live generation progress
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Failed to start generation.");
    } finally { setCreating(false); }
  }

  const countLabel = useMemo(() => `${total} ${total === 1 ? "note" : "notes"}`, [total]);

  return (
    <div className="ws-page sum-page notes-page">
      <header className="ws-header" style={{ ["--ws-accent" as string]: workspace?.color || "" }}>
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← {workspace?.name || "Workspace"}</Link>
        <div className="ws-header-right">
          <button className="ws-btn primary" onClick={() => { setPresetDocId(undefined); setCreateError(null); setShowModal(true); }}>
            ＋ New note
          </button>
        </div>
      </header>

      <div className="sum-list-col notes-list-col">
        <div className="ws-page-title">
          <div>
            <h1>📝 Smart Notes</h1>
            <p>{countLabel} · your editable knowledge base</p>
          </div>
        </div>

        <NotesToolbar
          search={searchInput} onSearch={setSearchInput}
          type={type} onType={(v) => { setType(v); setPage(1); }}
          pinned={pinned} onPinned={(v) => { setPinned(v); setPage(1); }}
          archived={archived} onArchived={(v) => { setArchived(v); setPage(1); }}
          sortBy={sortBy} order={order}
          onSort={(f, o) => { setSortBy(f); setOrder(o); setPage(1); }}
        />

        {tags.length > 0 && (
          <div className="note-tag-rail">
            <button className={`note-tag-chip${tagId === "" ? " active" : ""}`} onClick={() => { setTagId(""); setPage(1); }}>
              All
            </button>
            {tags.map((t) => (
              <button
                key={t.id}
                className={`note-tag-chip${tagId === t.id ? " active" : ""}`}
                style={{ ["--tag" as string]: t.color }}
                onClick={() => { setTagId(tagId === t.id ? "" : t.id); setPage(1); }}
              >
                {t.name} <span className="note-tag-count">{t.note_count}</span>
              </button>
            ))}
          </div>
        )}

        {error && <div className="ws-error-banner">{error}</div>}

        {loading ? (
          <div className="ws-grid sum-grid">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="ws-card skeleton" />)}
          </div>
        ) : items.length === 0 ? (
          <div className="ws-empty">
            <div className="ws-empty-mark">📝</div>
            <h3>{search || tagId ? "No notes match your filters" : "No notes yet"}</h3>
            <p>{search || tagId ? "Try a different term or clear filters." : "Write a note or generate structured, cited notes from a document."}</p>
            {!search && !tagId && (
              <button className="ws-btn primary" onClick={() => setShowModal(true)}>＋ New note</button>
            )}
          </div>
        ) : (
          <div className="ws-grid sum-grid note-grid">
            {items.map((n) => (
              <NoteCard
                key={n.id}
                note={n}
                onOpen={(x) => openNote(x.id)}
                onPin={(x) => mutate(() => notesApi.updateNote(workspaceId, x.id, { is_pinned: !x.is_pinned }))}
                onFavorite={(x) => mutate(() => notesApi.updateNote(workspaceId, x.id, { is_favorite: !x.is_favorite }))}
                onArchive={(x) => mutate(() => notesApi.updateNote(workspaceId, x.id, { is_archived: !x.is_archived }))}
                onDuplicate={(x) => mutate(async () => { const c = await notesApi.duplicateNote(workspaceId, x.id); openNote(c.id); })}
                onDelete={confirmDelete}
              />
            ))}
          </div>
        )}

        {pages > 1 && (
          <div className="ws-pagination">
            <button className="ws-btn ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Prev</button>
            <span>Page {page} of {pages}</span>
            <button className="ws-btn ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next →</button>
          </div>
        )}
      </div>

      {showModal && (
        <NewNoteModal
          workspaceId={workspaceId}
          initialDocumentId={presetDocId}
          submitting={creating}
          serverError={createError}
          onBlank={handleBlank}
          onGenerate={handleGenerate}
          onClose={() => { setShowModal(false); setPresetDocId(undefined); }}
        />
      )}
    </div>
  );
}
