// Unified Multimodal Search (Phase 4, Module 3). Route: /workspace/:workspaceId/search
//
// One search box queries every modality (text, OCR, images, diagrams, tables, metadata). Shows the
// detected intent + activated retrievers, per-modality filters, a grouped/unified toggle, per-type
// result cards, and a per-result explanation panel (retriever, scores, fusion contributions,
// reranker). Clicking a result opens the source document at its page (reuses Module 3 navigation).

import { useCallback, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as searchApi from "../api/search";
import { ApiError } from "../api/client";
import type { SearchModality, SearchResponse, SearchResult } from "../types";

const MODALITY_META: Record<string, { icon: string; label: string; color: string }> = {
  text: { icon: "📝", label: "Text", color: "#6366f1" },
  ocr: { icon: "🔠", label: "OCR", color: "#0ea5e9" },
  image: { icon: "🖼", label: "Image", color: "#f59e0b" },
  diagram: { icon: "🏗", label: "Diagram", color: "#8b5cf6" },
  table: { icon: "▦", label: "Table", color: "#10b981" },
  metadata: { icon: "🏷", label: "Metadata", color: "#64748b" },
};
const ALL_MODALITIES: SearchModality[] = ["text", "ocr", "image", "diagram", "table", "metadata"];

export default function MultimodalSearch() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Set<SearchModality>>(new Set());
  const [grouped, setGrouped] = useState(false);
  const [rerank, setRerank] = useState(true);
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async (q: string) => {
    if (!q.trim()) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const body: searchApi.SearchBody = { query: q, rerank, explain: true, top_k: 20 };
      if (filters.size) body.modalities = Array.from(filters);
      setRes(await searchApi.search(workspaceId, body, controller.signal));
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Search failed.");
    } finally { setLoading(false); }
  }, [workspaceId, filters, rerank]);

  function toggleFilter(m: SearchModality) {
    setFilters((prev) => {
      const next = new Set(prev);
      next.has(m) ? next.delete(m) : next.add(m);
      return next;
    });
  }

  function openResult(r: SearchResult) {
    if (!r.document_id) return;
    navigate(`/workspace/${workspaceId}/document/${r.document_id}`, {
      state: r.page_number ? { citation: { page: r.page_number, text: r.content } } : undefined,
    });
  }

  const groups = useMemo(() => {
    if (!res || !grouped) return null;
    const g: Record<string, SearchResult[]> = {};
    res.results.forEach((r) => { (g[r.modality] ||= []).push(r); });
    return g;
  }, [res, grouped]);

  return (
    <div className="ws-page sum-page search-page">
      <header className="ws-header">
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← Workspace</Link>
      </header>

      <div className="search-body">
        <div className="ws-page-title"><div><h1>🔭 Multimodal Search</h1><p>Search text, OCR, images, diagrams, tables & metadata at once</p></div></div>

        <form className="search-bar" onSubmit={(e) => { e.preventDefault(); run(query); }}>
          <input value={query} onChange={(e) => setQuery(e.target.value)} autoFocus
                 placeholder="Ask anything — “explain the architecture diagram”, “values in the table”…" aria-label="Search query" />
          <button className="ws-btn primary" type="submit" disabled={loading || !query.trim()}>{loading ? "Searching…" : "Search"}</button>
        </form>

        <div className="search-controls">
          <div className="search-filters">
            {ALL_MODALITIES.map((m) => (
              <button key={m} type="button" className={`search-chip${filters.has(m) ? " active" : ""}`}
                      style={{ ["--m" as string]: MODALITY_META[m].color }} onClick={() => toggleFilter(m)}>
                {MODALITY_META[m].icon} {MODALITY_META[m].label}
              </button>
            ))}
            {filters.size > 0 && <button className="search-chip clear" onClick={() => setFilters(new Set())}>✕ clear</button>}
          </div>
          <div className="search-toggles">
            <label className="search-toggle"><input type="checkbox" checked={grouped} onChange={(e) => setGrouped(e.target.checked)} /> Grouped</label>
            <label className="search-toggle"><input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} /> Cross-modal rerank</label>
          </div>
        </div>

        {error && <div className="ws-error-banner">{error}</div>}

        {res && (
          <div className="search-intent">
            <span>Searched <strong>{res.intents.length}</strong> modalities:</span>
            {res.intents.map((m) => (
              <span key={m} className={`search-intent-chip${res.detected.includes(m) ? " detected" : ""}`}
                    style={{ ["--m" as string]: MODALITY_META[m]?.color || "#888" }}>
                {MODALITY_META[m]?.icon} {m} <em>×{res.weights[m]?.toFixed(2)}</em>
              </span>
            ))}
            <span className="search-timing">{res.total} results · {res.total_ms.toFixed(0)}ms (fuse {res.fusion_ms.toFixed(0)} · rerank {res.rerank_ms.toFixed(0)})</span>
          </div>
        )}

        {res && res.total === 0 && !loading && (
          <div className="ws-empty"><div className="ws-empty-mark">🔭</div><h3>No results</h3><p>Try different terms, or process documents (multimodal + vision) to make their visuals searchable.</p></div>
        )}

        {res && groups ? (
          Object.entries(groups).map(([m, items]) => (
            <div key={m} className="search-group">
              <h3 className="search-group-title" style={{ color: MODALITY_META[m]?.color }}>{MODALITY_META[m]?.icon} {MODALITY_META[m]?.label} ({items.length})</h3>
              {items.map((r) => <ResultCard key={r.key} r={r} onOpen={openResult} />)}
            </div>
          ))
        ) : (
          res?.results.map((r) => <ResultCard key={r.key} r={r} onOpen={openResult} />)
        )}
      </div>
    </div>
  );
}

function ResultCard({ r, onOpen }: { r: SearchResult; onOpen: (r: SearchResult) => void }) {
  const [showExp, setShowExp] = useState(false);
  const meta = MODALITY_META[r.modality] || { icon: "•", label: r.modality, color: "#888" };
  return (
    <div className="search-result" style={{ ["--m" as string]: meta.color }}>
      <div className="search-result-main" onClick={() => onOpen(r)} role="button" tabIndex={0}
           onKeyDown={(e) => e.key === "Enter" && onOpen(r)}>
        <span className="search-result-badge">{meta.icon} {meta.label}</span>
        <div className="search-result-body">
          {r.title && <div className="search-result-title">{r.title}</div>}
          <p className="search-result-content">{r.content || <em>(no preview)</em>}</p>
          <div className="search-result-foot">
            <span className="search-conf">conf {Math.round(r.confidence * 100)}%</span>
            {r.page_number != null && <span>p.{r.page_number}</span>}
            {r.explanation && r.explanation.contributing_modalities.length > 1 && (
              <span className="search-multi">⛓ {r.explanation.contributing_modalities.join(" + ")}</span>
            )}
          </div>
        </div>
      </div>
      {r.explanation && (
        <button className="search-why" onClick={() => setShowExp((s) => !s)}>{showExp ? "▾" : "▸"} why</button>
      )}
      {showExp && r.explanation && (
        <div className="search-explanation">
          <Row label="Retriever" value={r.explanation.retriever} />
          <Row label="Raw → normalized" value={`${r.explanation.raw_score.toFixed(3)} → ${r.explanation.normalized_score.toFixed(3)}`} />
          <Row label="Fusion score" value={r.explanation.fusion_score.toFixed(4)} />
          <Row label="Contributions" value={Object.entries(r.explanation.fusion_contributions).map(([k, v]) => `${k}:${v.toFixed(4)}`).join("  ")} />
          {r.explanation.reranker_score != null && <Row label="Reranker" value={r.explanation.reranker_score.toFixed(3)} />}
          <Row label="Final rank" value={`#${r.explanation.final_rank}`} />
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return <div className="search-exp-row"><span className="search-exp-label">{label}</span><span className="search-exp-value">{value}</span></div>;
}
