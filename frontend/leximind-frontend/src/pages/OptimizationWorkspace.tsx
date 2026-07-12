// AI Optimization Workspace (Phase 8, Module 3) — the self-optimizing control room.
// Optimize a query (preview the plan: model routing + pipeline + recommendations + savings),
// run it optimized through the real pipeline, and review cost/quality/cache/policy.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  POLICY_LABEL, TIER_COLOR, dashboard as fetchDashboard, getPolicy, preview as fetchPreview, providerColor,
  recIcon, runOptimized, setPolicy as putPolicy,
  type Dashboard, type OptimizationPlan, type Policy, type RunResult,
} from "../api/optimization";
import "../styles/optimization.css";

type Tab = "optimize" | "cost" | "cache" | "history";
const POLICIES: Policy[] = ["balanced", "lowest_cost", "highest_quality", "fastest", "research", "offline", "developer", "enterprise"];

export default function OptimizationWorkspace() {
  const { workspaceId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("optimize");
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [policy, setPolicyState] = useState<Policy>("balanced");
  const [query, setQuery] = useState("");
  const [plan, setPlan] = useState<OptimizationPlan | null>(null);
  const [run, setRun] = useState<RunResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setDash(await fetchDashboard(workspaceId));
      setPolicyState((await getPolicy(workspaceId)).current);
    } catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load."); }
  }, [workspaceId]);
  useEffect(() => { refresh(); }, [refresh]);

  async function doPreview() {
    if (!query.trim()) return;
    setBusy(true); setError(""); setRun(null);
    try { setPlan(await fetchPreview(workspaceId, query, policy)); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Preview failed."); }
    finally { setBusy(false); }
  }
  async function doRun() {
    if (!query.trim()) return;
    setBusy(true); setError("");
    try { const r = await runOptimized(workspaceId, query, policy); setRun(r); setPlan(r.plan); refresh(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Run failed."); }
    finally { setBusy(false); }
  }
  async function changePolicy(p: Policy) {
    setPolicyState(p);
    try { await putPolicy(workspaceId, p); refresh(); } catch { /* ignore */ }
  }

  const opt = dash?.cost_analysis.optimization;

  return (
    <div className="op-page">
      <header className="op-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>⚙️ AI Optimization</h1>
        <div className="op-policy-pick">
          <span>Policy</span>
          <select value={policy} onChange={(e) => changePolicy(e.target.value as Policy)}>
            {POLICIES.map((p) => <option key={p} value={p}>{POLICY_LABEL[p]}</option>)}
          </select>
        </div>
      </header>
      {error && <p className="op-error" onClick={() => setError("")}>{error} ✕</p>}

      {dash && opt && (
        <div className="op-stat-row">
          <Stat label="Optimized runs" v={opt.runs} />
          <Stat label="Cache hits" v={opt.cache_hits} />
          <Stat label="Avg savings" v={`${Math.round(opt.avg_savings * 100)}%`} color="#10b981" />
          <Stat label="Est. spend" v={`$${opt.total_estimated_cost.toFixed(4)}`} />
          <Stat label="vs baseline" v={`$${opt.total_baseline_cost.toFixed(4)}`} />
        </div>
      )}

      <nav className="op-tabs">
        {(["optimize", "cost", "cache", "history"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>

      {tab === "optimize" && (
        <>
          <div className="op-query">
            <input value={query} placeholder="Enter a query to optimize…" onChange={(e) => setQuery(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && doPreview()} />
            <button disabled={busy} onClick={doPreview}>Preview plan</button>
            <button disabled={busy} className="op-run" onClick={doRun}>{busy ? "…" : "Run optimized"}</button>
          </div>

          {plan && (
            <div className="op-plan">
              <div className="op-plan-head">
                <span className="op-tier" style={{ background: TIER_COLOR[plan.profile.tier] }}>{plan.profile.tier}</span>
                <span className="op-model" style={{ borderColor: providerColor(plan.model.provider) }}>
                  <span className="op-dot" style={{ background: providerColor(plan.model.provider) }} />{plan.model.name}
                </span>
                <span className={`op-cache ${plan.cache_decision === "hit" ? "hit" : ""}`}>
                  cache {plan.cache_decision}
                </span>
                <span className="op-savings">↓ {Math.round(plan.estimated_savings * 100)}% · ${plan.estimated_cost.toFixed(5)} <s>${plan.baseline_cost.toFixed(5)}</s></span>
              </div>
              <p className="op-rationale">{plan.rationale}</p>

              <div className="op-stages">
                <Stage title="🔀 Model routing" rows={plan.candidates.slice(0, 4).map((c) => (
                  [c.model, `${c.score.toFixed(2)} · $${c.est_cost.toFixed(5)} · q${c.quality}`]))} />
                <Stage title="🔎 Retrieval" rows={[
                  ["top_k", String(plan.retrieval.top_k)], ["rerank", plan.retrieval.rerank_depth ? `@${plan.retrieval.rerank_depth}` : "off"],
                  ["graph", plan.retrieval.use_graph ? `×${plan.retrieval.graph_hops}` : "off"], ["early stop", String(plan.retrieval.early_stop)]]} />
                <Stage title="🧠 Context" rows={[
                  ["budget", `${plan.context.token_budget} tok`], ["compression", plan.context.compression],
                  ["dedup", String(plan.context.dedup)], ["citations", String(plan.context.preserve_citations)]]} />
                <Stage title="✍️ Prompt" rows={[["template", plan.prompt.template], ["version", plan.prompt.version], ["compress", String(plan.prompt.compress)]]} />
              </div>

              {plan.recommendations.length > 0 && (
                <div className="op-recs">
                  <h4>Recommendations</h4>
                  {plan.recommendations.map((r, i) => (
                    <div className="op-rec" key={i}>
                      <span className="op-rec-icon">{recIcon(r.kind)}</span>
                      <span className="op-rec-msg">{r.message}</span>
                      <span className="op-rec-save">−{Math.round(r.estimated_savings * 100)}%</span>
                    </div>
                  ))}
                </div>
              )}

              {run && (
                <div className="op-answer">
                  <h4>Answer {run.result.cache_used && <span className="op-cached">♻️ from cache</span>}</h4>
                  <p>{run.result.answer || <em className="op-muted">(no answer)</em>}</p>
                  <div className="op-answer-meta">
                    tokens {run.result.tokens} · actual ${run.result.actual_cost.toFixed(5)} ·
                    verification {run.result.verification_status ?? "—"} · saved {Math.round(run.savings * 100)}%
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {tab === "cost" && dash && (
        <div className="op-cost">
          <div className="op-stat-row">
            <Stat label="Total tokens" v={dash.cost_analysis.total_tokens} />
            <Stat label="Total cost" v={`$${dash.cost_analysis.total_cost.toFixed(4)}`} />
            <Stat label="Avg $/req" v={`$${dash.cost_analysis.avg_cost_per_request.toFixed(5)}`} />
          </div>
          <h4>Top cost sources</h4>
          <table className="op-table">
            <thead><tr><th>Source</th><th>Cost</th><th>Tokens</th></tr></thead>
            <tbody>
              {dash.cost_analysis.top_cost_sources.map((s) => (
                <tr key={s.source}><td>{s.source}</td><td>${s.cost.toFixed(5)}</td><td>{s.tokens}</td></tr>
              ))}
              {dash.cost_analysis.top_cost_sources.length === 0 && <tr><td colSpan={3} className="op-muted">No cost recorded yet.</td></tr>}
            </tbody>
          </table>
          <h4>Quality vs cost</h4>
          <div className="op-scatter">
            {dash.quality_vs_cost.map((p, i) => (
              <div key={i} className="op-scatter-pt" title={`${p.model} · q${p.quality} · $${p.cost.toFixed(5)}`}
                   style={{ left: `${Math.min(95, p.cost * 4000)}%`, bottom: `${p.quality * 90}%`,
                            background: p.cache_used ? "#10b981" : "#6366f1" }} />
            ))}
            <span className="op-axis-x">cost →</span><span className="op-axis-y">quality →</span>
          </div>
        </div>
      )}

      {tab === "cache" && dash && (
        <div className="op-cache-tab">
          <p className="op-cache-rec">{dash.cache.recommendation}</p>
          <div className="op-cols">
            {Object.entries(dash.cache.layers).map(([name, s]) => (
              <div className="op-cache-card" key={name}>
                <h4>{name}</h4>
                {Object.entries(s).map(([k, v]) => (
                  <div className="op-kv" key={k}><span>{k}</span><b>{String(v)}</b></div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === "history" && dash && (
        <table className="op-table">
          <thead><tr><th>Query</th><th>Policy</th><th>Model</th><th>Cache</th><th>Actual</th><th>Saved</th><th>Quality</th></tr></thead>
          <tbody>
            {dash.recent_runs.map((r) => (
              <tr key={r.id}>
                <td className="op-q">{r.query}</td><td>{r.policy}</td><td>{r.model}</td>
                <td>{r.cache_used ? "♻️" : "—"}</td><td>${r.actual_cost.toFixed(5)}</td>
                <td style={{ color: "#10b981" }}>{Math.round(r.savings * 100)}%</td><td>{r.quality_impact.toFixed(2)}</td>
              </tr>
            ))}
            {dash.recent_runs.length === 0 && <tr><td colSpan={7} className="op-muted">No optimized runs yet.</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Stat({ label, v, color }: { label: string; v: number | string; color?: string }) {
  return <div className="op-stat"><span className="op-stat-v" style={color ? { color } : undefined}>{v}</span><span className="op-stat-l">{label}</span></div>;
}

function Stage({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="op-stage">
      <h5>{title}</h5>
      {rows.map(([k, v], i) => <div className="op-kv" key={i}><span>{k}</span><b>{v}</b></div>)}
    </div>
  );
}
