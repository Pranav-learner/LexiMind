// CitationPanel — the "source of truth" side panel for any AI citation (Phase 3, Module 8).
//
// Given a citation id (or a chunk id to resolve), it fetches the full intelligence: metadata +
// scores, references grouped by type (where the evidence is used), related knowledge (Obsidian-
// style backlinks), and a deterministic "Why was this cited?" explanation. It has its own
// navigation history so exploring a related citation feels like browsing, and it reuses Module 3
// to open the PDF at the exact page. Used by the Knowledge Explorer and openable from anywhere.

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as citeApi from "../../api/citations";
import { getDocumentByVector } from "../../api/viewer";
import { ApiError } from "../../api/client";
import type { CitationDetail, CitationExplanation, CitationReferenceType, RelatedKnowledge } from "../../types";

interface Props {
  ws: string;
  citationId?: string;
  chunkId?: string;
  onClose?: () => void;
}

const TYPE_META: Record<CitationReferenceType, { icon: string; label: string; route: (ws: string, r: RefLite) => string }> = {
  message: { icon: "💬", label: "Chats", route: (ws, r) => `/workspace/${ws}/chat/${r.ref_parent_id}` },
  summary: { icon: "📄", label: "Summaries", route: (ws, r) => `/workspace/${ws}/summaries/${r.ref_parent_id}` },
  note: { icon: "📝", label: "Notes", route: (ws, r) => `/workspace/${ws}/notes/${r.ref_parent_id}` },
  flashcard: { icon: "🎴", label: "Flashcards", route: (ws, r) => `/workspace/${ws}/flashcards/deck/${r.ref_parent_id}` },
};

interface RefLite { ref_parent_id: string | null }

export default function CitationPanel({ ws, citationId, chunkId, onClose }: Props) {
  const navigate = useNavigate();
  const [stack, setStack] = useState<string[]>([]);        // navigation history of citation ids
  const [detail, setDetail] = useState<CitationDetail | null>(null);
  const [related, setRelated] = useState<RelatedKnowledge | null>(null);
  const [explanation, setExplanation] = useState<CitationExplanation | null>(null);
  const [showExplain, setShowExplain] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const currentId = stack[stack.length - 1];

  // Resolve the initial citation (by id or by chunk).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        let d: CitationDetail;
        if (citationId) d = await citeApi.getCitation(ws, citationId);
        else if (chunkId) d = await citeApi.citationByChunk(ws, { chunk_id: chunkId });
        else throw new Error("No citation specified");
        if (!alive) return;
        setStack([d.id]);
        setDetail(d);
      } catch (err) {
        if (!alive) return;
        setError(err instanceof ApiError ? err.message : "Citation not found.");
        setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [ws, citationId, chunkId]);

  // Load detail/related/explain whenever the current citation changes.
  const load = useCallback(async (id: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    setShowExplain(false);
    setExplanation(null);
    try {
      const [d, r] = await Promise.all([
        citeApi.getCitation(ws, id, controller.signal),
        citeApi.relatedKnowledge(ws, id, controller.signal),
      ]);
      setDetail(d);
      setRelated(r);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Failed to load citation.");
    } finally {
      setLoading(false);
    }
  }, [ws]);

  useEffect(() => { if (currentId) load(currentId); }, [currentId, load]);

  const pushCitation = (id: string) => setStack((s) => [...s, id]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));

  async function openExplain() {
    setShowExplain(true);
    if (!explanation && currentId) {
      try { setExplanation(await citeApi.explainCitation(ws, currentId)); } catch { /* ignore */ }
    }
  }

  async function openInPdf() {
    if (!detail?.document_id) return;
    try {
      const doc = await getDocumentByVector(ws, detail.document_id);
      navigate(`/workspace/${ws}/document/${doc.id}`, { state: { citation: { page: detail.page_number, text: detail.citation_text } } });
    } catch { /* best effort */ }
  }

  const conf = detail?.confidence ?? null;
  const confPct = conf != null ? Math.round(conf * 100) : null;
  const confBand = conf == null ? "unknown" : conf >= 0.75 ? "high" : conf >= 0.5 ? "moderate" : "low";

  return (
    <aside className="cite-panel">
      <header className="cite-panel-head">
        <div className="cite-panel-nav">
          {stack.length > 1 && <button className="ws-icon-btn" onClick={back} title="Back">←</button>}
          <span className="cite-panel-title">🔎 Citation Intelligence</span>
        </div>
        {onClose && <button className="ws-icon-btn" onClick={onClose} aria-label="Close">✕</button>}
      </header>

      {error ? (
        <div className="cite-panel-body"><div className="ws-error-banner">{error}</div></div>
      ) : loading && !detail ? (
        <div className="cite-panel-body cite-panel-loading"><span className="ws-brand-mark spin">🧠</span></div>
      ) : detail ? (
        <div className="cite-panel-body">
          {/* breadcrumbs — full source traceability */}
          <nav className="cite-breadcrumbs" aria-label="Source path">
            <span>Workspace</span><span className="sep">›</span>
            <button className="cite-crumb-link" onClick={openInPdf} disabled={!detail.document_id}>Document</button>
            <span className="sep">›</span>
            <span>Page {detail.page_number ?? "?"}</span><span className="sep">›</span>
            <span className="cite-crumb-chunk">{detail.chunk_id || "chunk"}</span>
          </nav>

          {/* evidence */}
          <div className="cite-evidence">
            <div className={`cite-conf-ring ${confBand}`} title={`${confBand} confidence`}>
              <span>{confPct != null ? `${confPct}%` : "—"}</span>
            </div>
            <blockquote className="cite-evidence-text">{detail.citation_text || "(no evidence text)"}</blockquote>
          </div>

          <div className="cite-actions">
            <button className="ws-btn primary" onClick={openInPdf} disabled={!detail.document_id}>📄 Open in PDF</button>
            <button className="ws-btn ghost" onClick={openExplain}>💡 Why cited?</button>
          </div>

          {/* metadata cards */}
          <div className="cite-meta-grid">
            <MetaCard label="Confidence" value={confPct != null ? `${confPct}%` : "—"} tone={confBand} />
            <MetaCard label="Evidence score" value={detail.evidence_score != null ? detail.evidence_score.toFixed(2) : "—"} />
            <MetaCard label="References" value={detail.reference_count} />
            <MetaCard label="Page" value={detail.page_number ?? "—"} />
            {detail.document && <MetaCard label="Doc citations" value={detail.document.citation_count} />}
            {detail.reranker_score != null && <MetaCard label="Reranker" value={detail.reranker_score.toFixed(2)} />}
          </div>

          {/* explain (toggle) */}
          {showExplain && (
            <section className="cite-section cite-explain">
              <h4>💡 Why the AI cited this</h4>
              {explanation ? (
                <>
                  <p className="cite-explain-summary">{explanation.summary}</p>
                  <ul className="cite-factors">
                    {explanation.factors.map((f, i) => (
                      <li key={i}><strong>{f.label}{f.score != null ? ` · ${Math.round(f.score * 100)}%` : ""}:</strong> {f.detail}</li>
                    ))}
                  </ul>
                  <details className="cite-path">
                    <summary>Retrieval path</summary>
                    <ol>{explanation.retrieval_path.map((p, i) => <li key={i}>{p}</li>)}</ol>
                  </details>
                </>
              ) : <p className="cite-muted">Composing explanation…</p>}
            </section>
          )}

          {/* references grouped by type */}
          <section className="cite-section">
            <h4>🔗 Used in <span className="note-count-badge">{detail.reference_count}</span></h4>
            {(["message", "summary", "note", "flashcard"] as CitationReferenceType[]).map((t) => {
              const refs = detail.references.filter((r) => r.reference_type === t);
              if (refs.length === 0) return null;
              return (
                <div key={t} className="cite-ref-group">
                  <span className="cite-ref-group-head">{TYPE_META[t].icon} {TYPE_META[t].label} ({refs.length})</span>
                  {refs.slice(0, 8).map((r) => (
                    <button key={r.id} className="cite-ref-item" title="Open" onClick={() => navigate(TYPE_META[t].route(ws, r))}>
                      {r.ref_title || "(untitled)"}
                    </button>
                  ))}
                </div>
              );
            })}
          </section>

          {/* related knowledge / backlinks */}
          <section className="cite-section">
            <h4>🧭 Related knowledge</h4>
            {related && related.related.length > 0 ? (
              <div className="cite-related-list">
                {related.related.slice(0, 12).map((r, i) => (
                  <button
                    key={i}
                    className={`cite-related-item rel-${r.relationship}`}
                    disabled={!r.citation_id}
                    onClick={() => r.citation_id && pushCitation(r.citation_id)}
                    title={r.relationship === "co_reference" ? "Co-cited with this evidence" : "Same document"}
                  >
                    <span className="cite-related-rel">{r.relationship === "co_reference" ? "⛓ co-cited" : "📎 same doc"}</span>
                    <span className="cite-related-text">{r.citation_text || r.chunk_id || "chunk"}</span>
                    {r.page_number != null && <span className="cite-related-page">p.{r.page_number}</span>}
                  </button>
                ))}
              </div>
            ) : (
              <p className="cite-muted">No related evidence yet — cite this concept elsewhere to build connections.</p>
            )}
          </section>
        </div>
      ) : null}
    </aside>
  );
}

function MetaCard({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className={`cite-meta-card${tone ? ` tone-${tone}` : ""}`}>
      <span className="cite-meta-value">{value}</span>
      <span className="cite-meta-label">{label}</span>
    </div>
  );
}
