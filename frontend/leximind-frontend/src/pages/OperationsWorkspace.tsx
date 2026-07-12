// AI Operations Workspace (Phase 8, Module 2) — production observability for developers/SRE.
// Metrics dashboard · distributed trace explorer with a span waterfall · cost · health · alerts.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  HEALTH_COLOR, SEVERITY_COLOR, componentColor, createRule, dashboard as fetchDashboard, deleteRule,
  evaluateAlerts, getTrace, listRules, listTraces, sourceColor, traceQuery,
  type AlertRule, type Dashboard, type TraceDetail, type TraceRow,
} from "../api/observability";
import "../styles/observability.css";

type Tab = "dashboard" | "traces" | "cost" | "alerts";

export default function OperationsWorkspace() {
  const { workspaceId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("dashboard");
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [traces, setTraces] = useState<TraceRow[]>([]);
  const [trace, setTrace] = useState<TraceDetail | null>(null);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try { setDash(await fetchDashboard(workspaceId)); setTraces(await listTraces(workspaceId)); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load."); }
  }, [workspaceId]);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { if (tab === "alerts") listRules(workspaceId).then(setRules).catch(() => {}); }, [tab, workspaceId]);

  async function runTraceQuery() {
    if (!query.trim()) return;
    setBusy(true); setError("");
    try { const t = await traceQuery(workspaceId, query); setTrace(t); setTab("traces"); refresh(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Trace query failed."); }
    finally { setBusy(false); }
  }
  async function openTrace(id: string) {
    try { setTrace(await getTrace(workspaceId, id)); } catch (e) { setError(e instanceof ApiError ? e.message : "Failed."); }
  }
  async function addRule() {
    const name = prompt("Rule name:", "High p95 latency"); if (!name) return;
    const metric = prompt("Metric (p95_latency_ms / error_rate / total_cost / total_tokens):", "p95_latency_ms"); if (!metric) return;
    const threshold = Number(prompt("Threshold:", "8000")); if (isNaN(threshold)) return;
    try { await createRule(workspaceId, { name, metric, comparator: "gt", threshold, severity: "warning" }); listRules(workspaceId).then(setRules); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Failed."); }
  }
  async function evalAlerts() { try { await evaluateAlerts(workspaceId); refresh(); } catch { /* ignore */ } }

  const m = dash?.metrics;

  return (
    <div className="ob-page">
      <header className="ob-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🛰️ AI Operations</h1>
        {dash && <span className="ob-health" style={{ background: HEALTH_COLOR[dash.health.status] }}>{dash.health.status}</span>}
        <div className="ob-tracequery">
          <input value={query} placeholder="Run a traced query…" onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runTraceQuery()} />
          <button disabled={busy} onClick={runTraceQuery}>{busy ? "…" : "Trace"}</button>
        </div>
      </header>
      {error && <p className="ob-error" onClick={() => setError("")}>{error} ✕</p>}

      <nav className="ob-tabs">
        {(["dashboard", "traces", "cost", "alerts"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>

      {tab === "dashboard" && dash && m && (
        <>
          <div className="ob-stat-row">
            <Stat label="Requests" v={m.requests} /><Stat label="Error rate" v={`${Math.round(m.error_rate * 100)}%`} color={m.error_rate > 0.2 ? "#ef4444" : undefined} />
            <Stat label="p95 latency" v={`${Math.round(m.latency_ms.p95)}ms`} /><Stat label="Tokens" v={m.tokens_total} />
            <Stat label="Cost" v={`$${m.cost_total.toFixed(4)}`} /><Stat label="Alerts" v={dash.active_alerts.length} color={dash.active_alerts.length ? "#ef4444" : undefined} />
          </div>
          {dash.active_alerts.length > 0 && (
            <div className="ob-alerts-banner">
              {dash.active_alerts.map((a, i) => <span key={i} className="ob-alert-chip" style={{ background: SEVERITY_COLOR[a.severity] }}>⚠ {a.message}</span>)}
            </div>
          )}
          <div className="ob-cols">
            <div>
              <h4>By source</h4>
              {Object.entries(m.by_source).sort(([, a], [, b]) => b.count - a.count).map(([src, b]) => (
                <div className="ob-source-row" key={src}>
                  <span className="ob-src-name"><span className="ob-dot" style={{ background: sourceColor(src) }} />{src}</span>
                  <span className="ob-src-meta">{b.count} · {Math.round(b.mean_ms)}ms · {Math.round(b.error_rate * 100)}% err</span>
                </div>
              ))}
            </div>
            <div>
              <h4>Health</h4>
              {Object.entries(dash.health.checks).map(([c, h]) => (
                <div className="ob-health-row" key={c}>
                  <span className="ob-dot" style={{ background: HEALTH_COLOR[h.status] }} /><b>{c}</b>
                  <span className="ob-muted">{h.detail}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {tab === "traces" && (
        <div className="ob-traces">
          <div className="ob-trace-list">
            {traces.map((t) => (
              <button key={t.id} className={`ob-trace-item ${trace?.id === t.id ? "is-active" : ""}`} onClick={() => openTrace(t.id)}>
                <span className="ob-dot" style={{ background: t.status === "error" ? "#ef4444" : "#10b981" }} />
                <span className="ob-trace-op">{t.operation}</span>
                <span className="ob-trace-meta">{Math.round(t.total_ms)}ms · {t.span_count} spans</span>
              </button>
            ))}
            {traces.length === 0 && <p className="ob-muted">No traces. Run a traced query above.</p>}
          </div>
          <div className="ob-trace-detail">
            {!trace && <div className="ob-empty">Select a trace to see its span waterfall.</div>}
            {trace && (
              <>
                <h3>{trace.operation} <span className="ob-muted">{Math.round(trace.total_ms)}ms · {trace.token_usage} tokens</span></h3>
                <div className="ob-waterfall">
                  {trace.waterfall.map((w, i) => (
                    <div className="ob-wf-row" key={i}>
                      <span className="ob-wf-name" style={{ paddingLeft: w.depth * 14 }}>{w.name}</span>
                      <div className="ob-wf-track">
                        <div className="ob-wf-bar" style={{ marginLeft: `${w.offset_pct}%`, width: `${Math.max(1, w.width_pct)}%`, background: w.status === "error" ? "#ef4444" : componentColor(w.component) }} />
                      </div>
                      <span className="ob-wf-ms">{Math.round(w.duration_ms)}ms</span>
                    </div>
                  ))}
                </div>
                <table className="ob-table">
                  <thead><tr><th>Span</th><th>Component</th><th>ms</th><th>tokens</th><th>status</th></tr></thead>
                  <tbody>
                    {trace.spans.map((s) => (
                      <tr key={s.id}><td>{s.name}</td><td>{s.component}</td><td>{Math.round(s.duration_ms)}</td><td>{s.tokens}</td>
                        <td style={{ color: s.status === "error" ? "#ef4444" : "#10b981" }}>{s.status}</td></tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        </div>
      )}

      {tab === "cost" && dash && (
        <div className="ob-cost">
          <div className="ob-stat-row">
            <Stat label="Total tokens" v={dash.cost.total_tokens} /><Stat label="Total cost" v={`$${dash.cost.total_cost.toFixed(4)}`} />
            <Stat label="Avg tokens/req" v={dash.cost.avg_tokens_per_request} /><Stat label="Avg $/req" v={`$${dash.cost.avg_cost_per_request.toFixed(5)}`} />
          </div>
          <h4>Top cost operations</h4>
          <table className="ob-table">
            <thead><tr><th>Operation</th><th>Tokens</th><th>Cost</th><th>Count</th></tr></thead>
            <tbody>
              {dash.cost.top_cost_operations.map((o) => (
                <tr key={o.operation}><td>{o.operation}</td><td>{o.tokens}</td><td>${o.cost.toFixed(5)}</td><td>{o.count}</td></tr>
              ))}
              {dash.cost.top_cost_operations.length === 0 && <tr><td colSpan={4} className="ob-muted">No cost recorded yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === "alerts" && (
        <div className="ob-alerts">
          <div className="ob-alert-actions">
            <button onClick={addRule}>+ Add rule</button>
            <button onClick={evalAlerts}>Evaluate now</button>
          </div>
          <table className="ob-table">
            <thead><tr><th>Name</th><th>Metric</th><th>Condition</th><th>Severity</th><th></th></tr></thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td><td>{r.metric}</td><td>{r.comparator} {r.threshold}</td>
                  <td><span style={{ color: SEVERITY_COLOR[r.severity] }}>{r.severity}</span></td>
                  <td><button className="ob-danger" onClick={() => deleteRule(workspaceId, r.id).then(() => listRules(workspaceId).then(setRules))}>×</button></td>
                </tr>
              ))}
              {rules.length === 0 && <tr><td colSpan={5} className="ob-muted">No custom rules (built-in rules always run).</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({ label, v, color }: { label: string; v: number | string; color?: string }) {
  return <div className="ob-stat"><span className="ob-stat-v" style={color ? { color } : undefined}>{v}</span><span className="ob-stat-l">{label}</span></div>;
}
