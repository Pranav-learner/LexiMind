// Graph Reasoning Inspector (Phase 7, Module 3) — developer tools for graph reasoning & explainable AI.
// Reasoning paths + inferred relationships + confidence flow + root causes + verification + explanation.
// (The visual knowledge workspace is Module 4; this is the reasoning-inspection/debug surface.)
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  confidenceColor, listReasoningLogs, reason, reasoningStats,
  type ReasoningLog, type ReasoningResult,
} from "../api/reasoning";
import "../styles/reasoning.css";

type Tab = "paths" | "inferences" | "confidence" | "rootcause" | "explanation" | "logs";

export default function GraphReasoningInspector() {
  const { workspaceId = "" } = useParams();
  const [query, setQuery] = useState("");
  const [hops, setHops] = useState(3);
  const [directed, setDirected] = useState(false);
  const [result, setResult] = useState<ReasoningResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("paths");
  const [logs, setLogs] = useState<ReasoningLog[]>([]);
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const abort = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    try { setLogs(await listReasoningLogs(workspaceId)); setStats(await reasoningStats(workspaceId)); } catch { /* ignore */ }
  }, [workspaceId]);
  useEffect(() => { refresh(); }, [refresh]);

  async function run() {
    if (!query.trim()) return;
    setRunning(true); setError(""); setResult(null); setTab("paths");
    const ctrl = new AbortController(); abort.current = ctrl;
    try {
      setResult(await reason(workspaceId, { query, hops, directed, dependency: true }, ctrl.signal));
      refresh();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Reasoning failed."); }
    finally { setRunning(false); }
  }

  const conf = result?.confidence ?? null;

  return (
    <div className="gr-page">
      <header className="gr-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🧩 Graph Reasoning</h1>
        <Link to={`/workspace/${workspaceId}/memory`} className="gr-muted">Semantic Memory →</Link>
      </header>

      {stats && (
        <div className="gr-stats-bar">
          <span><b>{String((stats as { reasonings?: number }).reasonings ?? 0)}</b> reasonings</span>
          <span><b>{String((stats as { inferred_relationships?: number }).inferred_relationships ?? 0)}</b> inferred edges</span>
          <span>cache hit-rate <b>{String((stats.cache as { hit_rate?: number })?.hit_rate ?? 0)}</b></span>
        </div>
      )}

      <div className="gr-search">
        <input value={query} placeholder="Reason, e.g. 'how does Paging relate to the Operating System?'"
          onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} />
        <label>hops <select value={hops} onChange={(e) => setHops(Number(e.target.value))}>
          {[1, 2, 3, 4, 5].map((h) => <option key={h} value={h}>{h}</option>)}</select></label>
        <label className="gr-check"><input type="checkbox" checked={directed} onChange={(e) => setDirected(e.target.checked)} /> directed</label>
        <button className="gr-run" disabled={running} onClick={run}>{running ? "Reasoning…" : "Reason"}</button>
      </div>
      {error && <p className="gr-error">{error}</p>}

      {result && (
        <>
          <div className="gr-summary">
            <span className="gr-label">Entities:</span>
            {result.seeds.map((s) => <span key={s.id} className="gr-chip">{s.name}</span>)}
            {conf && (
              <span className="gr-conf" style={{ color: confidenceColor(conf.overall) }}>
                confidence {Math.round(conf.overall * 100)}% ({conf.band})
              </span>
            )}
            {result.verification && (
              <span className={`gr-verif ${result.verification.graph_consistency ? "ok" : "bad"}`}>
                {result.verification.graph_consistency ? "✓ consistent" : "✕ inconsistent"}
              </span>
            )}
            <span className="gr-cx">{result.complexity.paths} paths · {result.complexity.inferences} inferences · depth {result.complexity.max_depth}{result.cache_hit && " · cached"}</span>
          </div>

          <nav className="gr-tabs">
            {(["paths", "inferences", "confidence", "rootcause", "explanation", "logs"] as Tab[]).map((t) => (
              <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
            ))}
          </nav>

          {tab === "paths" && (
            <ul className="gr-paths">
              {result.paths.map((p, i) => (
                <li key={i}>
                  <span className="gr-path-chain">{p.chain}</span>
                  <span className="gr-path-meta" style={{ color: confidenceColor(p.path_confidence) }}>
                    {Math.round(p.path_confidence * 100)}% · {p.length} hop{p.length > 1 ? "s" : ""}
                  </span>
                </li>
              ))}
              {result.paths.length === 0 && <li className="gr-muted">No reasoning paths — build a richer graph first.</li>}
            </ul>
          )}

          {tab === "inferences" && (
            <ul className="gr-inferences">
              {result.inferences.map((r, i) => (
                <li key={i}>
                  <span className="gr-inf-rel">{r.source} <b>{r.rel_type}</b> {r.target}</span>
                  <span className="gr-inf-badge">inferred</span>
                  <span className="gr-inf-meta">{Math.round(r.confidence * 100)}% · via {r.via.join(", ") || "direct"}</span>
                  <span className="gr-inf-deriv">{r.derivation}</span>
                </li>
              ))}
              {result.inferences.length === 0 && <li className="gr-muted">No implicit relationships inferred.</li>}
            </ul>
          )}

          {tab === "confidence" && conf && (
            <div className="gr-conf-panel">
              <p className="gr-explain">{conf.explanation}</p>
              {conf.signals.map((s) => (
                <div className="gr-sig" key={s.name}>
                  <span className="gr-sig-name">{s.name.replace(/_/g, " ")}</span>
                  <span className="gr-bar"><span className="gr-bar-fill" style={{ width: `${Math.round(s.value * 100)}%`, background: confidenceColor(s.value) }} /></span>
                  <span className="gr-sig-val">{Math.round(s.value * 100)}%</span><span className="gr-sig-w">×{s.weight.toFixed(2)}</span>
                </div>
              ))}
              <p className="gr-muted">edge confidence avg {conf.edge_confidence_avg} · path confidences {conf.path_confidence.map((x) => Math.round(x * 100) + "%").join(", ")}</p>
            </div>
          )}

          {tab === "rootcause" && (
            <div className="gr-rootcause">
              <h4>Root causes / foundational dependencies</h4>
              <ul>
                {result.root_causes.map((rc, i) => (
                  <li key={i}><b>{rc.entity}</b> <span className="gr-muted">depth {rc.depth} · {Math.round(rc.confidence * 100)}%</span></li>
                ))}
                {result.root_causes.length === 0 && <li className="gr-muted">No terminal dependencies (try directed mode).</li>}
              </ul>
              <h4>Dependency chains</h4>
              <ul className="gr-chains">
                {result.dependencies.slice(0, 12).map((d, i) => (
                  <li key={i}>{d.chain.join(" → ")}{d.is_root_cause && <span className="gr-rc-badge">root cause</span>}</li>
                ))}
              </ul>
            </div>
          )}

          {tab === "explanation" && <pre className="gr-json">{JSON.stringify(result.explanation, null, 2)}</pre>}

          {tab === "logs" && (
            <table className="gr-table">
              <thead><tr><th>Query</th><th>Seeds</th><th>Paths</th><th>Inferences</th><th>Conf</th><th>Verify</th><th>ms</th></tr></thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id}>
                    <td>{l.query.slice(0, 36)}</td><td>{l.seed_count}</td><td>{l.paths_found}</td>
                    <td>{l.inference_count}</td><td>{Math.round(l.overall_confidence * 100)}%</td>
                    <td>{l.verification_status}</td><td>{Math.round(l.total_ms)}</td>
                  </tr>
                ))}
                {logs.length === 0 && <tr><td colSpan={7} className="gr-muted">No reasoning yet.</td></tr>}
              </tbody>
            </table>
          )}
        </>
      )}
      {!result && !running && <div className="gr-empty">Ask a reasoning question — the engine finds multi-hop paths, infers relationships, and explains its confidence.</div>}
    </div>
  );
}
