// Temporal Search (Phase 5, Module 3) — timeline-aware search over recordings. Route:
//   /workspace/:workspaceId/temporal
//
// Ask a natural question ("what did the professor say about deadlocks at 12:04?", "what happened after
// the scheduling discussion?") and the engine retrieves across transcript / speaker / topic / chapter /
// event / scene / frame / timestamp, fuses + reranks them, and returns timestamped results, a timeline
// view, the assembled timeline-aware prompt, and timestamp-preserving citations. Inspectable — no LLM
// answer is generated here (that arrives with the media chat module).

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import { listDocuments } from "../api/documents";
import {
  fmtTime,
  MODALITY_META,
  temporalSearch,
  type TemporalSearchResponse,
} from "../api/temporal";
import type { LibraryDocument } from "../types";
import TimelineBar from "../components/temporal/TimelineBar";
import TimestampCard from "../components/temporal/TimestampCard";
import "../styles/temporal.css";

const EXAMPLES = [
  "What did the speaker say about deadlocks?",
  "What was said at 0:20?",
  "What happened after the scheduling discussion?",
  "Which chapter covers memory management?",
];

export default function TemporalSearch() {
  const { workspaceId = "" } = useParams();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<string>("");        // "" = all recordings
  const [recordings, setRecordings] = useState<LibraryDocument[]>([]);
  const [resp, setResp] = useState<TemporalSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPrompt, setShowPrompt] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    listDocuments(workspaceId, { page_size: 100 })
      .then((r) => setRecordings(r.items.filter((d) => d.media_type === "audio" || d.media_type === "video")))
      .catch(() => undefined);
  }, [workspaceId]);

  const run = useCallback(
    async (q: string) => {
      if (!q.trim()) return;
      abort.current?.abort();
      const ctrl = new AbortController();
      abort.current = ctrl;
      setLoading(true);
      setError(null);
      try {
        const body = { query: q, top_k: 12, build_context: true, explain: true, ...(scope ? { document_id: scope } : {}) };
        setResp(await temporalSearch(workspaceId, body, ctrl.signal));
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof ApiError ? err.message : "Temporal search failed.");
      } finally {
        setLoading(false);
      }
    },
    [workspaceId, scope],
  );

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    run(query);
  };

  return (
    <div className="temporal-page">
      <header className="temporal-header">
        <Link to={`/workspace/${workspaceId}`} className="temporal-back">← Workspace</Link>
        <h1>⏱ Temporal Search</h1>
        <p className="temporal-sub">
          Timeline-aware retrieval over your recordings — by time, speaker, topic, chapter, event &amp; scene.
          Every result preserves its exact timestamp.
        </p>
      </header>

      <form className="temporal-bar" onSubmit={onSubmit}>
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask about a moment, speaker, topic, or timestamp…"
        />
        <select value={scope} onChange={(e) => setScope(e.target.value)} title="Scope">
          <option value="">All recordings</option>
          {recordings.map((d) => (
            <option key={d.id} value={d.id}>{d.display_name}</option>
          ))}
        </select>
        <button type="submit" disabled={loading}>{loading ? "Searching…" : "Search"}</button>
      </form>

      {!resp && (
        <div className="temporal-examples">
          {EXAMPLES.map((ex) => (
            <button key={ex} className="temporal-chip" onClick={() => { setQuery(ex); run(ex); }}>{ex}</button>
          ))}
        </div>
      )}

      {error && <div className="temporal-banner">{error}</div>}

      {resp && (
        <div className="temporal-results">
          <div className="temporal-meta">
            <span className="temporal-intents">
              {resp.intents.map((m) => {
                const meta = MODALITY_META[m];
                return (
                  <span key={m} className={`temporal-intent ${m === resp.primary ? "is-primary" : ""}`}
                    style={{ color: meta?.color }}>
                    {meta?.icon} {meta?.label || m}
                  </span>
                );
              })}
            </span>
            {resp.time_filter && (
              <span className="temporal-timefilter">⏱ anchored at {fmtTime(resp.time_filter.anchor_ms)}</span>
            )}
            <span className="temporal-timing">
              {resp.total} results · {resp.total_ms.toFixed(0)}ms
              (fuse {resp.fusion_ms.toFixed(0)} · rerank {resp.rerank_ms.toFixed(0)} · ctx {resp.context_ms.toFixed(0)})
            </span>
            {resp.prompt && (
              <button className="temporal-linkbtn" onClick={() => setShowPrompt((s) => !s)}>
                {showPrompt ? "Hide" : "View"} timeline prompt
              </button>
            )}
          </div>

          <TimelineBar results={resp.results} />

          {showPrompt && resp.prompt && (
            <section className="temporal-prompt">
              <h3>Timeline-aware prompt <span>({resp.citations.length} citations)</span></h3>
              <pre>{resp.prompt}</pre>
            </section>
          )}

          {!resp.results.length && <p className="temporal-empty">No matching moments found.</p>}
          <div className="temporal-cards">
            {resp.results.map((r) => (
              <TimestampCard key={r.key} ws={workspaceId} result={r} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
