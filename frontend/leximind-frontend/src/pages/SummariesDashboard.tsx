// The AI Summaries dashboard. Routes:
//   /workspace/:workspaceId/summaries
//   /workspace/:workspaceId/summaries/:summaryId
//
// Left: a toolbar + paginated grid of SummaryCard + a "New summary" button (opens SummaryTypeModal,
// POSTs, then navigates to the new summary showing live generation progress). Right/main: when
// :summaryId is set, SummaryViewer (which fetches detail and polls if the summary is not terminal).
// Owns all query state: debounced (300ms) search, type/status filters, sort, pagination. Each list
// fetch is guarded by an AbortController so a newer query aborts the older in-flight request.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import * as summaryApi from "../api/summaries";
import { getDocumentByVector } from "../api/viewer";
import { getWorkspace } from "../api/workspaces";
import { ApiError } from "../api/client";
import SummaryCard from "../components/summary/SummaryCard";
import SummaryToolbar from "../components/summary/SummaryToolbar";
import SummaryTypeModal from "../components/summary/SummaryTypeModal";
import SummaryViewer from "../components/summary/SummaryViewer";
import type {
  Summary,
  SummaryCitation,
  SummaryCreateInput,
  SummarySortField,
  SummaryStatusFilter,
  SummaryType,
  SortOrder,
  Workspace,
} from "../types";

const PAGE_SIZE = 12;

// Optional router state passed from the Document Library "✨ Summarize" action.
interface PresetState {
  summarize?: { document_id: string };
}

export default function SummariesDashboard() {
  const { workspaceId = "", summaryId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [items, setItems] = useState<Summary[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [type, setType] = useState<SummaryType | "">("");
  const [status, setStatus] = useState<SummaryStatusFilter>("any");
  const [sortBy, setSortBy] = useState<SummarySortField>("updated_at");
  const [order, setOrder] = useState<SortOrder>("desc");

  const [showModal, setShowModal] = useState(false);
  const [presetDocIds, setPresetDocIds] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const openSummary = useCallback(
    (id: string) => navigate(`/workspace/${workspaceId}/summaries/${id}`),
    [navigate, workspaceId],
  );

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

  // Honor a "Summarize this document" hand-off from the Document Library.
  useEffect(() => {
    const preset = (location.state as PresetState | null)?.summarize;
    if (preset?.document_id) {
      setPresetDocIds([preset.document_id]);
      setShowModal(true);
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      const res = await summaryApi.listSummaries(
        workspaceId,
        {
          page,
          page_size: PAGE_SIZE,
          search,
          summary_type: type || undefined,
          status,
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
      setError(err instanceof ApiError ? err.message : "Failed to load summaries.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, page, search, type, status, sortBy, order]);

  useEffect(() => {
    load();
    return () => abortRef.current?.abort();
  }, [load]);

  const onCitation = useCallback(
    async (c: SummaryCitation) => {
      try {
        const doc = await getDocumentByVector(workspaceId, c.document_id);
        navigate(`/workspace/${workspaceId}/document/${doc.id}`, {
          state: { citation: { page: c.page_number, text: c.citation_text } },
        });
      } catch {
        // best-effort; stay on the summary
      }
    },
    [navigate, workspaceId],
  );

  async function mutate(fn: () => Promise<unknown>) {
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    }
  }

  function renameSummary(s: Summary) {
    const next = window.prompt("Rename summary", s.title || "Untitled summary");
    if (next != null && next.trim() && next.trim() !== s.title) {
      mutate(() => summaryApi.renameSummary(workspaceId, s.id, next.trim()));
    }
  }

  function confirmDelete(s: Summary) {
    if (window.confirm(`Delete "${s.title || "Untitled summary"}"? It will be moved to trash (soft delete).`)) {
      mutate(async () => {
        await summaryApi.deleteSummary(workspaceId, s.id);
        if (summaryId === s.id) navigate(`/workspace/${workspaceId}/summaries`);
      });
    }
  }

  async function duplicate(s: Summary) {
    try {
      const copy = await summaryApi.duplicateSummary(workspaceId, s.id);
      await load();
      openSummary(copy.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Duplicate failed.");
    }
  }

  async function handleCreate(payload: SummaryCreateInput) {
    setCreating(true);
    setCreateError(null);
    try {
      const created = await summaryApi.createSummary(workspaceId, payload);
      setShowModal(false);
      setPresetDocIds([]);
      await load();
      openSummary(created.id); // viewer shows the live generation progress
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Failed to start generation.");
    } finally {
      setCreating(false);
    }
  }

  const hasViewer = !!summaryId;
  const countLabel = useMemo(
    () => `${total} ${total === 1 ? "summary" : "summaries"}`,
    [total],
  );

  return (
    <div className="ws-page sum-page">
      <header className="ws-header" style={{ ["--ws-accent" as string]: workspace?.color || "" }}>
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← {workspace?.name || "Workspace"}</Link>
        <div className="ws-header-right">
          <button
            className="ws-btn primary"
            onClick={() => {
              setPresetDocIds([]);
              setCreateError(null);
              setShowModal(true);
            }}
          >
            ✨ New summary
          </button>
        </div>
      </header>

      <div className={`sum-layout${hasViewer ? " has-viewer" : ""}`}>
        <div className="sum-list-col">
          <div className="ws-page-title">
            <div>
              <h1>📝 AI Summaries</h1>
              <p>{countLabel}</p>
            </div>
          </div>

          <SummaryToolbar
            search={searchInput}
            onSearch={setSearchInput}
            type={type}
            onType={(v) => { setType(v); setPage(1); }}
            status={status}
            onStatus={(v) => { setStatus(v); setPage(1); }}
            sortBy={sortBy}
            order={order}
            onSort={(f, o) => { setSortBy(f); setOrder(o); setPage(1); }}
          />

          {error && <div className="ws-error-banner">{error}</div>}

          {loading ? (
            <div className="ws-grid sum-grid">
              {Array.from({ length: 4 }).map((_, i) => <div key={i} className="ws-card skeleton" />)}
            </div>
          ) : items.length === 0 ? (
            <div className="ws-empty">
              <div className="ws-empty-mark">📝</div>
              <h3>{search ? "No summaries match your search" : "No summaries yet"}</h3>
              <p>{search ? "Try a different term." : "Generate an AI summary of a document or your whole workspace."}</p>
              {!search && (
                <button className="ws-btn primary" onClick={() => { setPresetDocIds([]); setShowModal(true); }}>
                  ✨ New summary
                </button>
              )}
            </div>
          ) : (
            <div className="ws-grid sum-grid">
              {items.map((s) => (
                <SummaryCard
                  key={s.id}
                  summary={s}
                  active={s.id === summaryId}
                  onOpen={(x) => openSummary(x.id)}
                  onRename={renameSummary}
                  onRegenerate={(x) => mutate(() => summaryApi.regenerateSummary(workspaceId, x.id))}
                  onDuplicate={duplicate}
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

        {hasViewer && (
          <div className="sum-view-col">
            <button
              className="ws-icon-btn sum-view-close"
              title="Close"
              aria-label="Close summary"
              onClick={() => navigate(`/workspace/${workspaceId}/summaries`)}
            >
              ✕
            </button>
            <SummaryViewer
              key={summaryId}
              ws={workspaceId}
              summaryId={summaryId!}
              onCitation={onCitation}
              onChanged={load}
              onDeleted={() => navigate(`/workspace/${workspaceId}/summaries`)}
              onOpenSummary={openSummary}
            />
          </div>
        )}
      </div>

      {showModal && (
        <SummaryTypeModal
          workspaceId={workspaceId}
          initialScope={presetDocIds.length ? "documents" : "workspace"}
          initialDocumentIds={presetDocIds}
          submitting={creating}
          serverError={createError}
          onSubmit={handleCreate}
          onClose={() => { setShowModal(false); setPresetDocIds([]); }}
        />
      )}
    </div>
  );
}
