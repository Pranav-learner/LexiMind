// Agent Orchestration Dashboard (Phase 6, Module 4) — watch a team of AI agents work a task graph.
// Shows the workflow graph (layered, colour-coded by node status), the execution timeline (agent
// messages), per-agent results, the unified output, and the final verification.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError } from "../api/client";
import {
  AGENT_ICON, NODE_STATUS_COLOR, WORKFLOW_STATUS_COLOR, getOrchestration, listOrchestrations,
  listTemplates, planWorkflow, retryOrchestration, runWorkflow,
  type OrchestrationDetail, type OrchestrationLog, type OrchestrationResult, type TaskGraph,
  type WorkflowTemplate,
} from "../api/orchestration";
import VerificationPanel from "../components/verification/VerificationPanel";
import type { VerificationReport } from "../api/verification";
import "../styles/orchestration.css";

type Tab = "output" | "graph" | "timeline" | "agents" | "verification";

// client-side topological layering (mirrors TaskGraph.layers())
function layersOf(graph: TaskGraph): string[][] {
  const remaining = new Map(graph.nodes.map((n) => [n.id, n]));
  const done = new Set<string>();
  const layers: string[][] = [];
  let guard = 0;
  while (remaining.size && guard++ < 50) {
    const ready = [...remaining.values()].filter((n) => n.depends_on.every((d) => done.has(d)));
    if (!ready.length) break;
    ready.sort((a, b) => a.priority - b.priority);
    layers.push(ready.map((n) => n.id));
    ready.forEach((n) => { done.add(n.id); remaining.delete(n.id); });
  }
  return layers;
}

export default function OrchestrationDashboard() {
  const { workspaceId = "" } = useParams();
  const [objective, setObjective] = useState("");
  const [docIds, setDocIds] = useState("");
  const [workflow, setWorkflow] = useState("");
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [preview, setPreview] = useState<TaskGraph | null>(null);
  const [result, setResult] = useState<OrchestrationResult | OrchestrationDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("output");
  const [history, setHistory] = useState<OrchestrationLog[]>([]);
  const abort = useRef<AbortController | null>(null);

  const docList = () => docIds.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean);
  const refreshHistory = useCallback(async () => {
    try { setHistory(await listOrchestrations(workspaceId)); } catch { /* ignore */ }
  }, [workspaceId]);

  useEffect(() => { refreshHistory(); }, [refreshHistory]);
  useEffect(() => { listTemplates(workspaceId).then(setTemplates).catch(() => setTemplates([])); }, [workspaceId]);

  useEffect(() => {
    if (!objective.trim() || workflow) { setPreview(null); return; }
    const t = setTimeout(() => {
      planWorkflow(workspaceId, { objective, document_ids: docList() })
        .then((r) => setPreview(r.graph)).catch(() => setPreview(null));
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objective, docIds, workflow, workspaceId]);

  async function run() {
    if (!objective.trim()) return;
    setRunning(true); setError(""); setResult(null); setTab("output");
    const ctrl = new AbortController(); abort.current = ctrl;
    try {
      const res = await runWorkflow(workspaceId,
        { objective, document_ids: docList(), workflow: workflow || undefined }, ctrl.signal);
      setResult(res); refreshHistory();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Workflow failed.");
    } finally { setRunning(false); }
  }

  async function open(id: string) {
    try { setResult(await getOrchestration(workspaceId, id)); setTab("output"); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not load run."); }
  }
  async function doRetry(id: string) {
    setRunning(true);
    try { setResult(await retryOrchestration(workspaceId, id)); refreshHistory(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Retry failed."); }
    finally { setRunning(false); }
  }

  const graph = result?.graph ?? preview ?? null;
  const nodeById = (id: string) => graph?.nodes.find((n) => n.id === id);
  const messages = (result && "timeline" in result ? result.timeline : (result as OrchestrationDetail | null)?.messages) ?? [];
  const nodeResults = (result && "node_results" in result ? result.node_results : null) ?? [];
  const out = result?.output ?? null;
  const finalVer = (result?.final_verification ?? null) as VerificationReport | null;
  const rid = result ? ("orchestration_id" in result ? result.orchestration_id : (result as OrchestrationDetail).id) : "";

  return (
    <div className="orc-page">
      <header className="orc-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🕹️ Agent Orchestration</h1>
        <Link to={`/workspace/${workspaceId}/agents`} className="orc-muted">Agent Workspace →</Link>
      </header>

      <div className="orc-grid">
        <section className="orc-config">
          <label className="orc-field">
            <span>Objective</span>
            <textarea rows={3} value={objective} onChange={(e) => setObjective(e.target.value)}
              placeholder="e.g. Compare these papers and generate a verified study guide" />
          </label>
          <label className="orc-field">
            <span>Document scope <em>(optional ids)</em></span>
            <input value={docIds} onChange={(e) => setDocIds(e.target.value)} placeholder="doc_… doc_…" />
          </label>
          <label className="orc-field">
            <span>Workflow template</span>
            <select value={workflow} onChange={(e) => setWorkflow(e.target.value)}>
              <option value="">— auto-decompose —</option>
              {templates.map((t) => <option key={t.name} value={t.name}>{t.name.replace(/_/g, " ")}</option>)}
            </select>
          </label>
          <button className="orc-run" disabled={running} onClick={run}>
            {running ? "Agents working…" : "Run workflow"}
          </button>
          {error && <p className="orc-error">{error}</p>}
          {graph && (
            <div className="orc-mini-graph">
              <h4>Task graph</h4>
              {layersOf(graph).map((layer, i) => (
                <div className="orc-mini-layer" key={i}>
                  {layer.map((id) => {
                    const n = nodeById(id)!;
                    return (
                      <span key={id} className="orc-mini-node"
                        style={{ borderColor: NODE_STATUS_COLOR[n.status] || "#cbd5e1" }}>
                        {AGENT_ICON[n.agent] || "•"} {id}{n.optional ? "*" : ""}
                      </span>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
        </section>

        <main className="orc-main">
          {!result && !running && <div className="orc-empty">Describe an objective — the planner decomposes it into a team of agents.</div>}
          {running && <div className="orc-empty">The orchestrator is planning, scheduling and running the agent team…</div>}

          {result && (
            <>
              <div className="orc-result-head">
                <div>
                  <h2>{out?.title || result.objective}</h2>
                  <p className="orc-muted">{result.workflow} · {(result.agents_used ?? []).join(", ")}</p>
                </div>
                <div className="orc-actions">
                  <span className="orc-status" style={{ background: WORKFLOW_STATUS_COLOR[result.status] || "#64748b" }}>
                    {result.status}
                  </span>
                  {"schedule" in result && (
                    <span className="orc-mini-stat">{result.schedule.completed}✓ {result.schedule.failed}✕ {result.schedule.recovered}⟳</span>
                  )}
                  <button onClick={() => doRetry(rid)}>Retry</button>
                </div>
              </div>

              <nav className="orc-tabs">
                {(["output", "graph", "timeline", "agents", "verification"] as Tab[]).map((t) => (
                  <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
                ))}
              </nav>

              {tab === "output" && (
                <article className="orc-output">
                  {out?.markdown ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{out.markdown}</ReactMarkdown> : <em>No output.</em>}
                </article>
              )}

              {tab === "graph" && graph && (
                <div className="orc-graph">
                  {layersOf(graph).map((layer, i) => (
                    <div className="orc-graph-layer" key={i}>
                      <div className="orc-graph-layer-label">Layer {i + 1}</div>
                      {layer.map((id) => {
                        const n = nodeById(id)!;
                        return (
                          <div key={id} className="orc-graph-node" style={{ borderLeftColor: NODE_STATUS_COLOR[n.status] }}>
                            <div className="orc-node-title">{AGENT_ICON[n.agent] || "•"} {n.id}</div>
                            <div className="orc-node-meta">
                              <span className="orc-node-status" style={{ color: NODE_STATUS_COLOR[n.status] }}>{n.status}</span>
                              {n.depends_on.length > 0 && <span>← {n.depends_on.join(", ")}</span>}
                              {n.attempts > 1 && <span>{n.attempts} attempts</span>}
                              {n.recovered_by && <span>recovered via {n.recovered_by}</span>}
                              {n.optional && <span className="orc-opt">optional</span>}
                            </div>
                            {n.result_summary && <div className="orc-node-summary">{n.result_summary}</div>}
                            {n.error && <div className="orc-node-error">{n.error}</div>}
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              )}

              {tab === "timeline" && (
                <ol className="orc-timeline">
                  {messages.map((m, i) => (
                    <li key={i} className={`orc-msg orc-msg-${m.type}`}>
                      <span className="orc-msg-at">{Math.round(m.at_ms)}ms</span>
                      <span className="orc-msg-type">{m.type}</span>
                      <span className="orc-msg-from">{m.sender} → {m.recipient}</span>
                      <span className="orc-msg-payload">{JSON.stringify(m.payload)}</span>
                    </li>
                  ))}
                </ol>
              )}

              {tab === "agents" && (
                <ul className="orc-agents">
                  {nodeResults.map((n) => (
                    <li key={n.node}>
                      <span className="orc-agent-dot" style={{ background: NODE_STATUS_COLOR[n.status] }} />
                      <span className="orc-agent-name">{AGENT_ICON[n.agent] || "•"} {n.node}</span>
                      <span className="orc-agent-status">{n.status}{n.optional ? " (optional)" : ""}</span>
                      <span className="orc-agent-sum">{n.summary}</span>
                      <span className="orc-agent-ms">{Math.round(n.latency_ms)}ms · {n.attempts}×</span>
                    </li>
                  ))}
                  {nodeResults.length === 0 && <li className="orc-muted">Open a completed run to see agent results.</li>}
                </ul>
              )}

              {tab === "verification" && (
                finalVer ? <VerificationPanel report={finalVer} />
                  : <p className="orc-muted">No final verification report.</p>
              )}
            </>
          )}
        </main>

        <aside className="orc-side">
          <h3>History</h3>
          <ul className="orc-history">
            {history.length === 0 && <li className="orc-muted">No runs yet.</li>}
            {history.map((o) => (
              <li key={o.id} onClick={() => open(o.id)}>
                <span className="orc-hist-status" style={{ background: WORKFLOW_STATUS_COLOR[o.status] || "#64748b" }} />
                <span className="orc-hist-main">
                  <span className="orc-hist-obj">{o.objective.slice(0, 42)}</span>
                  <span className="orc-hist-sub">{o.workflow} · {o.completed_tasks}/{o.node_count} · {Math.round(o.verification_confidence * 100)}%</span>
                </span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}
