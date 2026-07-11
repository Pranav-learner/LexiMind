// The Knowledge Explorer. Route: /workspace/:workspaceId/knowledge
//
// The workspace's citation intelligence hub: a stats header, a search/filter toolbar, a ranked
// list of every citation (deduped across chat/summaries/notes/flashcards), and the CitationPanel
// as a detail pane. Selecting a citation opens the panel; a ?chunk=<id> or ?citation=<id> query
// param opens it directly (used when jumping here from an AI answer). Search covers text, document,
// page, reference type, and confidence — the foundation for future semantic citation search.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import * as citeApi from "../api/citations";
import { getWorkspace } from "../api/workspaces";
import { ApiError } from "../api/client";
import CitationPanel from "../components/citations/CitationPanel";
import type {
  CitationIntel,
  CitationReferenceType,
  CitationStats,
  Workspace,
} from "../types";

const PAGE_SIZE = 20;

export default function KnowledgeExplorer() {
  const { workspaceId = "" } = useParams();
  const [params, setParams] = useSearchParams();

  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [stats, setStats] = useState<CitationStats | null>(null);
  const [items, setItems] = useState<CitationIntel[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [refType, setRefType] = useState<CitationReferenceType | "">("");
  const [minConf, setMinConf] = useState(0);

  const [selected, setSelected] = useState<{ citationId?: string; chunkId?: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Open the panel directly from a ?chunk / ?citation deep-link (jump from an AI answer).
  useEffect(() => {
    const chunk = params.get("chunk");
    const citation = params.get("citation");
    if (chunk) setSelected({ chunkId: chunk });
    else if (citation) setSelected({ citationId: citation });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let alive = true;
    getWorkspace(workspaceId).then((w) => alive && setWorkspace(w)).catch(() => {});
    return () => { alive = false; };
  }, [workspaceId]);

  useEffect(() => {
    const t = setTimeout(() => { setKeyword(searchInput); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const [res, st] = await Promise.all([
        citeApi.searchCitations(workspaceId, {
          page, page_size: PAGE_SIZE, keyword: keyword || undefined,
          reference_type: refType || undefined, min_confidence: minConf || undefined,
          sort_by: "reference_count", order: "desc",
        }, controller.signal),
        citeApi.citationStats(workspaceId, controller.signal),
      ]);
      setItems(res.items);
      setTotal(res.total);
      setPages(res.pages);
      setStats(st);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Failed to load citations.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, page, keyword, refType, minConf]);

  useEffect(() => { load(); return () => abortRef.current?.abort(); }, [load]);

  function select(c: CitationIntel) {
    setSelected({ citationId: c.id });
    setParams({ citation: c.id }, { replace: true });
  }

  function closePanel() {
    setSelected(null);
    setParams({}, { replace: true });
  }

  const hasPanel = !!selected;
  const countLabel = useMemo(() => `${total} ${total === 1 ? "citation" : "citations"}`, [total]);

  return (
    <div className="ws-page sum-page cite-page">
      <header className="ws-header" style={{ ["--ws-accent" as string]: workspace?.color || "" }}>
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← {workspace?.name || "Workspace"}</Link>
        <div className="ws-header-right">
          <button className="ws-btn ghost" onClick={() => citeApi.reindexCitations(workspaceId).then(load).catch(() => {})} title="Rebuild index">↻ Reindex</button>
        </div>
      </header>

      <div className={`cite-layout${hasPanel ? " has-panel" : ""}`}>
        <div className="cite-list-col">
          <div className="ws-page-title">
            <div>
              <h1>🔎 Knowledge Explorer</h1>
              <p>{countLabel} · every AI answer, fully traceable</p>
            </div>
          </div>

          {stats && (
            <div className="cite-stats-row">
              <Stat value={stats.total_citations} label="Citations" />
              <Stat value={stats.total_references} label="References" />
              <Stat value={stats.documents_cited} label="Documents" />
              <Stat value={`${Math.round(stats.avg_confidence * 100)}%`} label="Avg confidence" />
              <Stat value={stats.high_confidence} label="High-confidence" />
            </div>
          )}

          <div className="sum-toolbar cite-toolbar">
            <div className="sum-search">
              <span aria-hidden="true">🔍</span>
              <input type="search" placeholder="Search evidence text…" value={searchInput}
                     onChange={(e) => setSearchInput(e.target.value)} aria-label="Search citations" />
            </div>
            <select value={refType} onChange={(e) => { setRefType(e.target.value as CitationReferenceType | ""); setPage(1); }} aria-label="Reference type">
              <option value="">All sources</option>
              <option value="message">💬 Chats</option>
              <option value="summary">📄 Summaries</option>
              <option value="note">📝 Notes</option>
              <option value="flashcard">🎴 Flashcards</option>
            </select>
            <select value={String(minConf)} onChange={(e) => { setMinConf(Number(e.target.value)); setPage(1); }} aria-label="Min confidence">
              <option value="0">Any confidence</option>
              <option value="0.5">≥ 50%</option>
              <option value="0.7">≥ 70%</option>
              <option value="0.85">≥ 85%</option>
            </select>
          </div>

          {error && <div className="ws-error-banner">{error}</div>}

          {loading ? (
            <div className="cite-card-list">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="ws-card skeleton" style={{ height: 72 }} />)}</div>
          ) : items.length === 0 ? (
            <div className="ws-empty">
              <div className="ws-empty-mark">🔎</div>
              <h3>{keyword ? "No citations match" : "No citations yet"}</h3>
              <p>{keyword ? "Try a different term." : "Ask the AI, generate a summary, note, or flashcards — every cited source appears here."}</p>
            </div>
          ) : (
            <div className="cite-card-list">
              {items.map((c) => {
                const pct = c.confidence != null ? Math.round(c.confidence * 100) : null;
                const band = c.confidence == null ? "unknown" : c.confidence >= 0.75 ? "high" : c.confidence >= 0.5 ? "moderate" : "low";
                return (
                  <button key={c.id} className={`cite-list-item${selected?.citationId === c.id ? " active" : ""}`} onClick={() => select(c)}>
                    <span className={`cite-conf-dot ${band}`} title={`${pct ?? "—"}% confidence`}>{pct != null ? `${pct}` : "—"}</span>
                    <span className="cite-list-text">{c.citation_text || "(no evidence text)"}</span>
                    <span className="cite-list-meta">
                      {c.page_number != null && <span>p.{c.page_number}</span>}
                      <span className="cite-list-refs">🔗 {c.reference_count}</span>
                    </span>
                  </button>
                );
              })}
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

        {hasPanel && (
          <CitationPanel
            key={selected.citationId || selected.chunkId}
            ws={workspaceId}
            citationId={selected.citationId}
            chunkId={selected.chunkId}
            onClose={closePanel}
          />
        )}
      </div>
    </div>
  );
}

function Stat({ value, label }: { value: number | string; label: string }) {
  return <div className="cite-stat"><span className="cite-stat-value">{value}</span><span className="cite-stat-label">{label}</span></div>;
}
