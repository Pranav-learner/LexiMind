// The workspace dashboard: search / sort / filter / paginate a grid of workspace cards,
// and create / edit / archive / restore / delete them.
//
// Performance notes:
// - Search is debounced (300ms) so typing doesn't fire a request per keystroke.
// - Each fetch is guarded by an AbortController; a newer query aborts the older in-flight
//   request, preventing out-of-order state updates and duplicate work.
// - Cards are memoized (see WorkspaceCard) so unrelated cards don't re-render.

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api/workspaces";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import WorkspaceCard from "../components/workspace/WorkspaceCard";
import WorkspaceFormModal from "../components/workspace/WorkspaceFormModal";
import WorkspaceToolbar from "../components/workspace/WorkspaceToolbar";
import OrganizationSwitcher from "../components/collaboration/OrganizationSwitcher";
import type {
  ArchivedFilter,
  SortField,
  SortOrder,
  Workspace,
  WorkspaceFormValues,
} from "../types";

const PAGE_SIZE = 12;

export default function WorkspacesDashboard() {
  const { user, logout } = useAuth();

  const [items, setItems] = useState<Workspace[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState<ArchivedFilter>("active");
  const [sortBy, setSortBy] = useState<SortField>("updated_at");
  const [order, setOrder] = useState<SortOrder>("desc");

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Workspace | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

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
      const res = await api.listWorkspaces(
        { page, page_size: PAGE_SIZE, search, archived, sort_by: sortBy, order },
        controller.signal,
      );
      setItems(res.items);
      setTotal(res.total);
      setPages(res.pages);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return; // superseded
      setError(err instanceof ApiError ? err.message : "Failed to load workspaces.");
    } finally {
      setLoading(false);
    }
  }, [page, search, archived, sortBy, order]);

  useEffect(() => {
    load();
    return () => abortRef.current?.abort();
  }, [load]);

  async function handleCreate(values: WorkspaceFormValues) {
    setSaving(true);
    setFormError(null);
    try {
      await api.createWorkspace(values);
      setShowCreate(false);
      setPage(1);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create workspace.");
    } finally {
      setSaving(false);
    }
  }

  async function handleEdit(values: WorkspaceFormValues) {
    if (!editing) return;
    setSaving(true);
    setFormError(null);
    try {
      await api.updateWorkspace(editing.id, values);
      setEditing(null);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not save changes.");
    } finally {
      setSaving(false);
    }
  }

  async function mutate(fn: () => Promise<unknown>) {
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    }
  }

  function confirmDelete(ws: Workspace) {
    if (window.confirm(`Delete "${ws.name}"? It will be moved to trash (soft delete).`)) {
      mutate(() => api.deleteWorkspace(ws.id));
    }
  }

  return (
    <div className="ws-page">
      <header className="ws-header">
        <div className="ws-brand small">
          <span className="ws-brand-mark">🧠</span>
          <span>LexiMind</span>
        </div>
        <div className="ws-header-right" style={{ display: "flex", gap: 15, alignItems: "center" }}>
          <OrganizationSwitcher />
          <span className="ws-user">{user?.display_name || user?.email}</span>
          <button className="ws-btn ghost" onClick={logout}>Log out</button>
        </div>
      </header>

      <div className="ws-page-body">
        <div className="ws-page-title">
          <div>
            <h1>Workspaces</h1>
            <p>{total} {total === 1 ? "workspace" : "workspaces"}</p>
          </div>
          <button className="ws-btn primary" onClick={() => { setFormError(null); setShowCreate(true); }}>
            + New workspace
          </button>
        </div>

        <WorkspaceToolbar
          search={searchInput}
          onSearch={setSearchInput}
          archived={archived}
          onArchived={(v) => { setArchived(v); setPage(1); }}
          sortBy={sortBy}
          order={order}
          onSort={(f, o) => { setSortBy(f); setOrder(o); setPage(1); }}
        />

        {error && <div className="ws-error-banner">{error}</div>}

        {loading ? (
          <div className="ws-grid">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="ws-card skeleton" />)}
          </div>
        ) : items.length === 0 ? (
          <div className="ws-empty">
            <div className="ws-empty-mark">🗂️</div>
            <h3>{search ? "No workspaces match your search" : "No workspaces yet"}</h3>
            <p>{search ? "Try a different term." : "Create your first workspace to get started."}</p>
            {!search && (
              <button className="ws-btn primary" onClick={() => setShowCreate(true)}>
                + New workspace
              </button>
            )}
          </div>
        ) : (
          <div className="ws-grid">
            {items.map((w) => (
              <WorkspaceCard
                key={w.id}
                workspace={w}
                onEdit={(ws) => { setFormError(null); setEditing(ws); }}
                onArchive={(ws) => mutate(() => api.archiveWorkspace(ws.id))}
                onRestore={(ws) => mutate(() => api.restoreWorkspace(ws.id))}
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

      {showCreate && (
        <WorkspaceFormModal
          mode="create"
          submitting={saving}
          serverError={formError}
          onSubmit={handleCreate}
          onClose={() => setShowCreate(false)}
        />
      )}
      {editing && (
        <WorkspaceFormModal
          mode="edit"
          initial={editing}
          submitting={saving}
          serverError={formError}
          onSubmit={handleEdit}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
