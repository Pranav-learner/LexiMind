// Semantic Memory Explorer (Phase 7, Module 2) — developer tools for graph retrieval.
// Query → recognized entities → graph hits (scored/explained) → neighborhood + fusion breakdown + logs.
// (The final interactive Knowledge Workspace is Module 4; this is the retrieval-inspection surface.)
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  hitColor, listMemoryLogs, memoryStats, retrieveMemory,
  type MemoryLog, type RetrieveResult,
} from "../api/memory";
import "../styles/memory.css";

type Tab = "hits" | "context" | "fusion" | "timings" | "logs";

export default function SemanticMemoryExplorer() {
  const { workspaceId = "" } = useParams();
  const [query, setQuery] = useState("");
  const [hops, setHops] = useState(2);
  const [strategy, setStrategy] = useState("bfs");
  const [hybrid, setHybrid] = useState(false);
  const [result, setResult] = useState<RetrieveResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("hits");
  const [logs, setLogs] = useState<MemoryLog[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const abort = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    try { setLogs(await listMemoryLogs(workspaceId)); setStats(await memoryStats(workspaceId)); } catch { /* ignore */ }
  }, [workspaceId]);
  useEffect(() => { refresh(); }, [refresh]);

  async function run() {
    if (!query.trim()) return;
    setRunning(true); setError(""); setResult(null); setTab("hits");
    const ctrl = new AbortController(); abort.current = ctrl;
    try {
      setResult(await retrieveMemory(workspaceId, { query, hops, strategy, hybrid, limit: 20 }, ctrl.signal));
      refresh();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Retrieval failed."); }
    finally { setRunning(false); }
  }

  const graphMetrics = (stats?.graph as { entities?: number; relationships?: number }) || {};

  return (
    <div className="sm-page">
      <header className="sm-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🧠 Semantic Memory</h1>
        <Link to={`/workspace/${workspaceId}/graph`} className="sm-muted">Knowledge Graph →</Link>
      </header>

      {stats && (
        <div className="sm-stats-bar">
          <span><b>{graphMetrics.entities ?? 0}</b> entities</span>
          <span><b>{graphMetrics.relationships ?? 0}</b> relationships</span>
          <span>cache hit-rate <b>{String((stats.cache as { hit_rate?: number })?.hit_rate ?? 0)}</b></span>
          <span><b>{String((stats as { queries?: number }).queries ?? 0)}</b> queries</span>
        </div>
      )}

      <div className="sm-search">
        <input value={query} placeholder="Ask the graph, e.g. 'what does React depend on?'"
          onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} />
        <label>hops <select value={hops} onChange={(e) => setHops(Number(e.target.value))}>
          {[1, 2, 3, 4].map((h) => <option key={h} value={h}>{h}</option>)}</select></label>
        <label>strategy <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          <option value="bfs">bfs</option><option value="dfs">dfs</option></select></label>
        <label className="sm-check"><input type="checkbox" checked={hybrid} onChange={(e) => setHybrid(e.target.checked)} /> hybrid</label>
        <button className="sm-run" disabled={running} onClick={run}>{running ? "Retrieving…" : "Retrieve"}</button>
      </div>
      {error && <p className="sm-error">{error}</p>}

      {result && (
        <>
          <div className="sm-recognized">
            <span className="sm-label">Recognized entities:</span>
            {result.recognized_entities.length === 0 && <span className="sm-muted">none</span>}
            {result.recognized_entities.map((e) => (
              <span key={e.id} className="sm-chip">{e.name} <em>{e.type}</em></span>
            ))}
            <span className="sm-nb">neighborhood: {result.neighborhood.nodes} nodes · {result.neighborhood.edges} edges · max hop {result.neighborhood.max_hop}
              {result.cache_hit && " · cached"}{result.neighborhood.truncated && " · truncated"}</span>
          </div>

          <nav className="sm-tabs">
            {(["hits", "context", "fusion", "timings", "logs"] as Tab[]).map((t) => (
              <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
            ))}
          </nav>

          {tab === "hits" && (
            <ul className="sm-hits">
              {result.hits.map((h, i) => (
                <li key={i}>
                  <span className="sm-hit-kind" style={{ background: hitColor(h.kind) }}>{h.kind}</span>
                  <span className="sm-hit-text">{h.text}</span>
                  <span className="sm-hit-meta">hop {h.hop_distance} · score {h.score.toFixed(3)}</span>
                  <span className="sm-hit-sig">
                    {Object.entries(h.signals).filter(([k]) => k.startsWith("sig_")).slice(0, 4)
                      .map(([k, v]) => `${k.replace("sig_", "")} ${v.toFixed(2)}`).join(" · ")}
                  </span>
                </li>
              ))}
              {result.hits.length === 0 && <li className="sm-muted">No graph knowledge found — build the graph first.</li>}
            </ul>
          )}

          {tab === "context" && <pre className="sm-context">{result.context_text || "(empty)"}</pre>}

          {tab === "fusion" && (
            <table className="sm-table">
              <thead><tr><th>Key</th><th>Modality</th><th>Fusion score</th><th>Modalities</th><th>Content</th></tr></thead>
              <tbody>
                {result.fused.map((f, i) => (
                  <tr key={i}>
                    <td>{f.key}</td><td><span className="sm-hit-kind" style={{ background: hitColor(f.modality) }}>{f.modality}</span></td>
                    <td>{f.fusion_score.toFixed(5)}</td><td>{f.contributing_modalities.join(", ")}</td>
                    <td className="sm-fuse-content">{f.content}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {tab === "timings" && (
            <div className="sm-timings">
              {Object.entries(result.timings).map(([k, v]) => (
                <div className="sm-timing" key={k}><span>{k.replace("_ms", "")}</span><b>{v.toFixed(1)}ms</b></div>
              ))}
            </div>
          )}

          {tab === "logs" && (
            <table className="sm-table">
              <thead><tr><th>Query</th><th>Mode</th><th>Seeds</th><th>Neighborhood</th><th>Hits</th><th>Cache</th><th>ms</th></tr></thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id}>
                    <td>{l.query.slice(0, 40)}</td><td>{l.mode}</td><td>{l.seed_count}</td>
                    <td>{l.neighborhood_size}n/{l.edges_traversed}e</td><td>{l.hits_returned}</td>
                    <td>{l.cache_hit ? "✓" : ""}</td><td>{Math.round(l.total_ms)}</td>
                  </tr>
                ))}
                {logs.length === 0 && <tr><td colSpan={7} className="sm-muted">No queries yet.</td></tr>}
              </tbody>
            </table>
          )}
        </>
      )}
      {!result && !running && <div className="sm-empty">Ask a question — Semantic Memory resolves it to graph entities and retrieves knowledge.</div>}
    </div>
  );
}
