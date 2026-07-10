// The Document Library dashboard. Route: /workspace/:workspaceId/library.
//
// Owns all query state: debounced (300ms) search, archived / indexed / file_type / language
// filters, sort, pagination (PAGE_SIZE=12), and grid/list view. Each fetch is guarded by an
// AbortController so a newer query aborts the older in-flight request. Cards are memoized.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as docApi from "../api/documents";
import { getWorkspace } from "../api/workspaces";
import { ApiError } from "../api/client";
import DocumentCard from "../components/document/DocumentCard";
import DocumentToolbar from "../components/document/DocumentToolbar";
import DocumentDetailDrawer from "../components/document/DocumentDetailDrawer";
import UploadDropzone from "../components/document/UploadDropzone";
import type {
  ArchivedFilter,
  DocumentSortField,
  IndexedFilter,
  LibraryDocument,
  SortOrder,
  Workspace,
} from "../types";

const PAGE_SIZE = 12;

export default function DocumentsLibrary() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const openViewer = (doc: LibraryDocument) =>
    navigate(`/workspace/${workspaceId}/document/${doc.id}`);

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [items, setItems] = useState<LibraryDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState<ArchivedFilter>("active");
  const [indexed, setIndexed] = useState<IndexedFilter>("any");
  const [fileType, setFileType] = useState("");
  const [language, setLanguage] = useState("");
  const [sortBy, setSortBy] = useState<DocumentSortField>("updated_at");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [view, setView] = useState<"grid" | "list">("grid");

  const [showUpload, setShowUpload] = useState(false);
  const [selected, setSelected] = useState<LibraryDocument | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // Workspace header (name + accent).
  useEffect(() => {
    let alive = true;
    getWorkspace(workspaceId)
      .then((w) => alive && setWorkspace(w))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [workspaceId]);

  // Debounce the search box → `search` (the value actually queried).
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const res = await docApi.listDocuments(
        workspaceId,
        {
          page,
          page_size: PAGE_SIZE,
          search,
          archived,
          indexed,
          file_type: fileType || undefined,
          language: language || undefined,
          sort_by: sortBy,
          order,
        },
        controller.signal,
      );
      setItems(res.items);
      setTotal(res.total);
      setPages(res.pages);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return; // superseded
      setError(err instanceof ApiError ? err.message : "Failed to load documents.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, page, search, archived, indexed, fileType, language, sortBy, order]);

  useEffect(() => {
    load();
    return () => abortRef.current?.abort();
  }, [load]);

  // Derive filter option lists from the current page's documents.
  const fileTypes = useMemo(
    () => Array.from(new Set(items.map((d) => d.file_type).filter(Boolean))).sort(),
    [items],
  );
  const languages = useMemo(
    () => Array.from(new Set(items.map((d) => d.language).filter(Boolean))).sort(),
    [items],
  );

  async function mutate(fn: () => Promise<unknown>) {
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    }
  }

  function renameDoc(doc: LibraryDocument) {
    const next = window.prompt("Rename document", doc.display_name || doc.filename);
    if (next != null && next.trim() && next.trim() !== doc.display_name) {
      mutate(() => docApi.updateDocument(workspaceId, doc.id, { display_name: next.trim() }));
    }
  }

  function confirmDelete(doc: LibraryDocument) {
    if (window.confirm(`Delete "${doc.display_name || doc.filename}"? It will be moved to trash (soft delete).`)) {
      mutate(() => docApi.deleteDocument(workspaceId, doc.id));
    }
  }

  return (
    <div className="ws-page">
      <header className="ws-header" style={{ ["--ws-accent" as string]: workspace?.color || "" }}>
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← {workspace?.name || "Workspace"}</Link>
        <div className="ws-header-right">
          <button className="ws-btn primary" onClick={() => setShowUpload((s) => !s)}>
            {showUpload ? "Close upload" : "+ Upload documents"}
          </button>
        </div>
      </header>

      <div className="ws-page-body">
        <div className="ws-page-title">
          <div>
            <h1>📚 Document Library</h1>
            <p>{total} {total === 1 ? "document" : "documents"}</p>
          </div>
        </div>

        {showUpload && (
          <section className="ws-panel">
            <UploadDropzone workspaceId={workspaceId} onUploaded={load} />
          </section>
        )}

        <DocumentToolbar
          search={searchInput}
          onSearch={setSearchInput}
          archived={archived}
          onArchived={(v) => { setArchived(v); setPage(1); }}
          indexed={indexed}
          onIndexed={(v) => { setIndexed(v); setPage(1); }}
          fileType={fileType}
          onFileType={(v) => { setFileType(v); setPage(1); }}
          language={language}
          onLanguage={(v) => { setLanguage(v); setPage(1); }}
          sortBy={sortBy}
          order={order}
          onSort={(f, o) => { setSortBy(f); setOrder(o); setPage(1); }}
          view={view}
          onView={setView}
          fileTypes={fileTypes}
          languages={languages}
        />

        {error && <div className="ws-error-banner">{error}</div>}

        {loading ? (
          <div className={view === "grid" ? "ws-grid" : "doc-list"}>
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="ws-card skeleton" />)}
          </div>
        ) : items.length === 0 ? (
          <div className="ws-empty">
            <div className="ws-empty-mark">📄</div>
            <h3>{search ? "No documents match your search" : "No documents yet"}</h3>
            <p>{search ? "Try a different term." : "Upload a PDF to build your library."}</p>
            {!search && (
              <button className="ws-btn primary" onClick={() => setShowUpload(true)}>
                + Upload documents
              </button>
            )}
          </div>
        ) : (
          <div className={view === "grid" ? "ws-grid" : "doc-list"}>
            {items.map((d) => (
              <DocumentCard
                key={d.id}
                doc={d}
                view={view}
                onOpen={setSelected}
                onView={openViewer}
                onRename={renameDoc}
                onArchive={(doc) => mutate(() => docApi.archiveDocument(workspaceId, doc.id))}
                onRestore={(doc) => mutate(() => docApi.restoreDocument(workspaceId, doc.id))}
                onReindex={(doc) => mutate(() => docApi.reindexDocument(workspaceId, doc.id))}
                onDelete={confirmDelete}
              />
            ))}
          </div>
        )}

        {pages > 1 && (
          <div className="ws-pagination">
            <button className="ws-btn ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              ← Prev
            </button>
            <span>Page {page} of {pages}</span>
            <button className="ws-btn ghost" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next →
            </button>
          </div>
        )}
      </div>

      {selected && (
        <DocumentDetailDrawer
          workspaceId={workspaceId}
          doc={selected}
          onClose={() => setSelected(null)}
          onChanged={(updated) => {
            setSelected(updated);
            load();
          }}
        />
      )}
    </div>
  );
}
