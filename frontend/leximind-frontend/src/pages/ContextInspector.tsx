// Multimodal Context Inspector (Phase 4, Module 4). Route: /workspace/:workspaceId/context
//
// A developer/debug view of the Multimodal Context Engineering Engine: enter a query and inspect the
// assembled context — the detected intent + weights, per-stage metrics (dedup reduction, compression
// ratio, token usage, latency), the adaptive token-budget allocation per modality, the ordered
// context blocks with per-evidence scores + selection reasons + ranking explanation, the cross-modal
// citations, and the raw assembled prompt. Makes the engine fully inspectable.

import { useCallback, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as ctxApi from "../api/context";
import { ApiError } from "../api/client";
import type { ContextEvidence, ContextResponse } from "../types";

const MODALITY_META: Record<string, { icon: string; color: string }> = {
  text: { icon: "📝", color: "#6366f1" }, ocr: { icon: "🔠", color: "#0ea5e9" },
  image: { icon: "🖼", color: "#f59e0b" }, diagram: { icon: "🏗", color: "#8b5cf6" },
  table: { icon: "▦", color: "#10b981" }, metadata: { icon: "🏷", color: "#64748b" },
};

export default function ContextInspector() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [res, setRes] = useState<ContextResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    if (!query.trim()) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true); setError(null);
    try {
      setRes(await ctxApi.buildContext(workspaceId, { query, developer: true, explain: true }, controller.signal));
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Build failed.");
    } finally { setLoading(false); }
  }, [workspaceId, query]);

  const m = res?.metrics;

  return (
    <div className="ws-page sum-page ctx-page">
      <header className="ws-header">
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← Workspace</Link>
      </header>

      <div className="ctx-body">
        <div className="ws-page-title"><div><h1>🧠 Context Inspector</h1><p>Inspect how multimodal evidence is assembled into the LLM prompt</p></div></div>

        <form className="search-bar" onSubmit={(e) => { e.preventDefault(); run(); }}>
          <input value={query} onChange={(e) => setQuery(e.target.value)} autoFocus
                 placeholder="Enter a query — “explain the architecture diagram”, “what is deadlock”…" aria-label="Query" />
          <button className="ws-btn primary" type="submit" disabled={loading || !query.trim()}>{loading ? "Building…" : "Build context"}</button>
        </form>

        {error && <div className="ws-error-banner">{error}</div>}

        {res && (
          <>
            <div className="ctx-intent">
              <span>Intent <strong>{res.primary_intent}</strong> · modalities:</span>
              {res.modalities.map((mod) => (
                <span key={mod} className="ctx-intent-chip" style={{ ["--m" as string]: MODALITY_META[mod]?.color || "#888" }}>
                  {MODALITY_META[mod]?.icon} {mod} <em>×{res.weights[mod]?.toFixed(2)}</em>
                </span>
              ))}
            </div>

            {m && (
              <div className="ctx-metrics">
                <Metric label="Retrieved" value={m.retrieved} />
                <Metric label="After dedup" value={m.after_dedup} />
                <Metric label="Included" value={m.included} />
                <Metric label="Dropped" value={m.dropped} />
                <Metric label="Context tokens" value={m.context_tokens} />
                <Metric label="Dup. reduction" value={`${Math.round(m.duplicate_reduction * 100)}%`} />
                <Metric label="Compression" value={`${Math.round(m.compression_ratio * 100)}%`} />
                <Metric label="Total" value={`${m.total_ms.toFixed(0)}ms`} />
              </div>
            )}

            {res.budget.length > 0 && (
              <div className="ctx-panel">
                <h3 className="ctx-h3">Token budget</h3>
                {res.budget.map((b) => (
                  <div key={b.modality} className="ctx-budget-row">
                    <span className="ctx-budget-label" style={{ color: MODALITY_META[b.modality]?.color }}>{MODALITY_META[b.modality]?.icon} {b.modality}</span>
                    <div className="ctx-budget-bar"><div className="ctx-budget-fill" style={{ width: `${b.allocated ? Math.min(100, (b.used / b.allocated) * 100) : 0}%`, background: MODALITY_META[b.modality]?.color }} /></div>
                    <span className="ctx-budget-num">{b.used} / {b.allocated}</span>
                  </div>
                ))}
              </div>
            )}

            <h3 className="ctx-h3">Assembled context ({res.blocks.length} blocks)</h3>
            {res.blocks.map((block) => (
              <div key={block.modality} className="ctx-block">
                <div className="ctx-block-head" style={{ borderColor: MODALITY_META[block.modality]?.color }}>
                  <span style={{ color: MODALITY_META[block.modality]?.color }}>{MODALITY_META[block.modality]?.icon} {block.header}</span>
                  <span className="ctx-block-tokens">{block.token_cost} tok</span>
                </div>
                {block.items.map((ev) => <EvidenceCard key={ev.key} ev={ev} onOpen={() => ev.document_id && navigate(`/workspace/${workspaceId}/document/${ev.document_id}`, { state: ev.page_number ? { citation: { page: ev.page_number, text: ev.content } } : undefined })} />)}
              </div>
            ))}

            {res.citations.length > 0 && (
              <div className="ctx-panel">
                <h3 className="ctx-h3">Citations ({res.citations.length})</h3>
                {res.citations.map((c, i) => (
                  <div key={i} className="ctx-citation">[{i + 1}] {MODALITY_META[c.modality]?.icon} {c.modality}{c.page_number != null ? ` · p.${c.page_number}` : ""} — {c.text.slice(0, 80)}</div>
                ))}
              </div>
            )}

            {res.prompt && (
              <div className="ctx-panel">
                <button className="ctx-h3 ctx-prompt-toggle" onClick={() => setShowPrompt((s) => !s)}>{showPrompt ? "▾" : "▸"} Assembled prompt ({res.metrics.prompt_tokens} tokens)</button>
                {showPrompt && <pre className="ctx-prompt">{res.prompt}</pre>}
              </div>
            )}

            {res.dropped.length > 0 && (
              <div className="ctx-panel">
                <h3 className="ctx-h3">Dropped ({res.dropped.length})</h3>
                {res.dropped.map((d, i) => <div key={i} className="ctx-dropped">{MODALITY_META[d.modality]?.icon} {d.modality} — {d.reason}</div>)}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return <div className="ctx-metric"><span className="ctx-metric-value">{value}</span><span className="ctx-metric-label">{label}</span></div>;
}

function EvidenceCard({ ev, onOpen }: { ev: ContextEvidence; onOpen: () => void }) {
  const [show, setShow] = useState(false);
  const meta = MODALITY_META[ev.modality] || { icon: "•", color: "#888" };
  return (
    <div className="ctx-evidence" style={{ ["--m" as string]: meta.color }}>
      <div className="ctx-evidence-main" onClick={onOpen} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
        <span className="ctx-ev-rank">#{ev.rank}</span>
        <div className="ctx-ev-body">
          <p className="ctx-ev-content">{ev.content || <em>(empty)</em>}</p>
          <div className="ctx-ev-foot">
            <span className="ctx-ev-score">score {ev.evidence_score.toFixed(3)}</span>
            <span>{ev.token_cost} tok</span>
            {ev.compressed && <span className="ctx-ev-tag">compressed</span>}
            {ev.contributing_modalities.length > 1 && <span className="ctx-ev-tag">⛓ {ev.contributing_modalities.join("+")}</span>}
            <span className="ctx-ev-reason">{ev.selection_reason}</span>
          </div>
        </div>
      </div>
      {ev.ranking_contributions && (
        <button className="ctx-ev-why" onClick={() => setShow((s) => !s)}>{show ? "▾" : "▸"} ranking</button>
      )}
      {show && ev.ranking_contributions && (
        <div className="ctx-ev-signals">
          {Object.entries(ev.ranking_contributions).map(([k, v]) => (
            <div key={k} className="ctx-signal"><span>{k}</span><div className="ctx-signal-bar"><div style={{ width: `${Math.min(100, v * 250)}%` }} /></div><span>{v.toFixed(3)}</span></div>
          ))}
        </div>
      )}
    </div>
  );
}
