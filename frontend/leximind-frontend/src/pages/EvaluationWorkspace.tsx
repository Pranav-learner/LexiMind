// Evaluation Workspace (Phase 8, Module 1) — developer quality dashboard + benchmark runner.
// Datasets · run a benchmark on a real pipeline · metric charts · regression + CI gate · A/B comparison.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  STATUS_COLOR, VERDICT_COLOR, compareRuns, dashboard as fetchDashboard, listDatasets, listPipelines,
  listRuns, metricColor, runBenchmark,
  type Comparison, type Dataset, type Pipeline, type RunLog, type RunResult,
} from "../api/evaluation";
import "../styles/evaluation.css";

type Tab = "dashboard" | "run" | "compare";

export default function EvaluationWorkspace() {
  const { workspaceId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("dashboard");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [runs, setRuns] = useState<RunLog[]>([]);
  const [dash, setDash] = useState<Awaited<ReturnType<typeof fetchDashboard>> | null>(null);
  const [dsId, setDsId] = useState("");
  const [pipeline, setPipeline] = useState("workspace_retrieval");
  const [useJudge, setUseJudge] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [cmpA, setCmpA] = useState(""); const [cmpB, setCmpB] = useState("");
  const [cmp, setCmp] = useState<{ comparison: Comparison } | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDatasets(await listDatasets(workspaceId));
      setRuns(await listRuns(workspaceId));
      setDash(await fetchDashboard(workspaceId));
    } catch { /* ignore */ }
  }, [workspaceId]);

  useEffect(() => { refresh(); listPipelines(workspaceId).then(setPipelines).catch(() => {}); }, [refresh, workspaceId]);
  useEffect(() => { if (datasets.length && !dsId) setDsId(datasets[0].id); }, [datasets, dsId]);

  async function run() {
    if (!dsId) { setError("Create a dataset first."); return; }
    setRunning(true); setError(""); setResult(null);
    try { setResult(await runBenchmark(workspaceId, { dataset_id: dsId, pipeline, use_judge: useJudge })); refresh(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Benchmark failed."); }
    finally { setRunning(false); }
  }
  async function compare() {
    if (!cmpA || !cmpB) return;
    try { setCmp(await compareRuns(workspaceId, cmpA, cmpB)); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Compare failed."); }
  }

  const metricRows = (m: Record<string, number>) => Object.entries(m).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="ev-page">
      <header className="ev-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>📊 Evaluation</h1>
        {dash && <span className="ev-muted">{dash.total_runs} runs · {dash.datasets} datasets · {dash.regressions} regressions</span>}
      </header>
      {error && <p className="ev-error" onClick={() => setError("")}>{error} ✕</p>}

      <nav className="ev-tabs">
        {(["dashboard", "run", "compare"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>

      {tab === "dashboard" && dash && (
        <>
          <div className="ev-stat-row">
            <Stat label="Runs" v={dash.total_runs} /><Stat label="Datasets" v={dash.datasets} />
            <Stat label="Regressions" v={dash.regressions} color={dash.regressions ? "#ef4444" : undefined} />
            <Stat label="Gate failures" v={dash.gate_failures} color={dash.gate_failures ? "#ef4444" : undefined} />
          </div>
          <table className="ev-table">
            <thead><tr><th>Pipeline</th><th>Label</th><th>Items</th><th>Key metrics</th><th>Regression</th><th>Gate</th><th>ms</th></tr></thead>
            <tbody>
              {dash.recent.map((r) => (
                <tr key={r.id}>
                  <td>{r.pipeline}</td><td>{r.label || ""}</td><td>{r.item_count}</td>
                  <td className="ev-metric-cell">
                    {["recall@5", "ndcg@5", "ground_truth_match", "hallucination_rate"].filter((k) => k in r.metrics).map((k) => (
                      <span key={k} className="ev-mini" style={{ color: metricColor(k, r.metrics[k]) }}>{k.replace("@", "@")} {r.metrics[k].toFixed(2)}</span>
                    ))}
                  </td>
                  <td><span style={{ color: STATUS_COLOR[r.regression_status] }}>{r.regression_status}</span></td>
                  <td>{r.gate_passed === null ? "—" : r.gate_passed ? "✓" : "✕"}</td>
                  <td>{Math.round(r.duration_ms)}</td>
                </tr>
              ))}
              {dash.recent.length === 0 && <tr><td colSpan={7} className="ev-muted">No runs yet — run a benchmark.</td></tr>}
            </tbody>
          </table>
        </>
      )}

      {tab === "run" && (
        <div className="ev-run">
          <div className="ev-run-config">
            <label>Dataset <select value={dsId} onChange={(e) => setDsId(e.target.value)}>
              {datasets.map((d) => <option key={d.id} value={d.id}>{d.name} v{d.version} ({d.item_count})</option>)}
            </select></label>
            <label>Pipeline <select value={pipeline} onChange={(e) => setPipeline(e.target.value)}>
              {pipelines.map((p) => <option key={p.name} value={p.name}>{p.name} ({p.kind})</option>)}
            </select></label>
            <label className="ev-check"><input type="checkbox" checked={useJudge} onChange={(e) => setUseJudge(e.target.checked)} /> LLM judge</label>
            <button className="ev-run-btn" disabled={running} onClick={run}>{running ? "Running…" : "Run benchmark"}</button>
          </div>

          {result && (
            <div className="ev-result">
              <div className="ev-result-head">
                <h3>{result.pipeline} · {result.item_count} items</h3>
                <span className="ev-gate" style={{ background: result.gate.passed ? "#10b981" : "#ef4444" }}>
                  gate {result.gate.passed ? "PASS" : "FAIL"}
                </span>
                <span style={{ color: STATUS_COLOR[result.regression_status] }}>{result.regression_status}</span>
              </div>
              {!result.gate.passed && <ul className="ev-gate-reasons">{result.gate.reasons.map((r, i) => <li key={i}>⚠ {r}</li>)}</ul>}
              <div className="ev-metrics-grid">
                {metricRows(result.metrics).map(([k, v]) => (
                  <div className="ev-metric" key={k}>
                    <span className="ev-metric-name">{k}</span>
                    <span className="ev-metric-val" style={{ color: metricColor(k, v) }}>{v < 1 && v > 0 ? v.toFixed(4) : v.toFixed(1)}</span>
                  </div>
                ))}
              </div>
              {result.regression && result.regression.deltas.length > 0 && (
                <>
                  <h4>vs baseline</h4>
                  <table className="ev-table">
                    <thead><tr><th>Metric</th><th>Current</th><th>Baseline</th><th>Δ</th><th>Verdict</th></tr></thead>
                    <tbody>
                      {result.regression.deltas.map((d) => (
                        <tr key={d.metric}><td>{d.metric}</td><td>{d.current}</td><td>{d.baseline}</td>
                          <td>{d.delta > 0 ? "+" : ""}{d.delta}</td>
                          <td style={{ color: VERDICT_COLOR[d.verdict] }}>{d.verdict}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {tab === "compare" && (
        <div className="ev-compare">
          <div className="ev-cmp-pick">
            <select value={cmpA} onChange={(e) => setCmpA(e.target.value)}>
              <option value="">Run A…</option>
              {runs.map((r) => <option key={r.id} value={r.id}>{r.label || r.pipeline} · {r.created_at?.slice(0, 16)}</option>)}
            </select>
            <span>vs</span>
            <select value={cmpB} onChange={(e) => setCmpB(e.target.value)}>
              <option value="">Run B…</option>
              {runs.map((r) => <option key={r.id} value={r.id}>{r.label || r.pipeline} · {r.created_at?.slice(0, 16)}</option>)}
            </select>
            <button onClick={compare}>Compare</button>
          </div>
          {cmp && (
            <>
              <p className="ev-winner">Winner: <b>{cmp.comparison.winner}</b> ({cmp.comparison.a_label} {cmp.comparison.a_wins} — {cmp.comparison.b_wins} {cmp.comparison.b_label})</p>
              <table className="ev-table">
                <thead><tr><th>Metric</th><th>{cmp.comparison.a_label}</th><th>{cmp.comparison.b_label}</th><th>Δ</th><th>Verdict</th></tr></thead>
                <tbody>
                  {cmp.comparison.per_metric.map((d) => (
                    <tr key={d.metric}><td>{d.metric}</td><td>{d.current}</td><td>{d.baseline}</td>
                      <td>{d.delta > 0 ? "+" : ""}{d.delta}</td>
                      <td style={{ color: VERDICT_COLOR[d.verdict] }}>{d.verdict}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, v, color }: { label: string; v: number; color?: string }) {
  return <div className="ev-stat"><span className="ev-stat-v" style={color ? { color } : undefined}>{v}</span><span className="ev-stat-l">{label}</span></div>;
}
