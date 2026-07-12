// Agent Debug Panel (Phase 6, Module 1) — a developer-facing view of the Agent Runtime. Route:
//   /workspace/:workspaceId/agent
//
// Run an agent request and inspect exactly how it executed: the planner's rationale + execution graph,
// the tools it selected and their results, the event timeline with timings, the PromptPackage that was
// handed to the single answer pathway, and the final answer. Also lists registered tools/agents and
// recent executions. This is intentionally low-level (for building/debugging agents), not an end-user
// chat — it exposes the internals the framework produces.

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  listAgents,
  listExecutions,
  listTools,
  previewPlan,
  runAgent,
  NODE_STATUS_COLOR,
  type AgentDescriptor,
  type ExecutionLog,
  type ExecutionPlan,
  type RunResponse,
  type ToolSpec,
} from "../api/agents";
import "../styles/agents.css";

type Tab = "answer" | "graph" | "tools" | "timeline" | "prompt";

export default function AgentDebugPanel() {
  const { workspaceId = "" } = useParams();
  const [query, setQuery] = useState("");
  const [run, setRun] = useState<RunResponse | null>(null);
  const [plan, setPlan] = useState<ExecutionPlan | null>(null);
  const [tools, setTools] = useState<ToolSpec[]>([]);
  const [agents, setAgents] = useState<AgentDescriptor[]>([]);
  const [history, setHistory] = useState<ExecutionLog[]>([]);
  const [tab, setTab] = useState<Tab>("answer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const refreshMeta = useCallback(() => {
    listTools(workspaceId).then(setTools).catch(() => undefined);
    listAgents(workspaceId).then(setAgents).catch(() => undefined);
    listExecutions(workspaceId).then(setHistory).catch(() => undefined);
  }, [workspaceId]);
  useEffect(() => { refreshMeta(); }, [refreshMeta]);

  // live plan preview as the user types (debounced), no execution
  useEffect(() => {
    if (!query.trim()) { setPlan(null); return; }
    const t = setTimeout(() => {
      previewPlan(workspaceId, { query }).then(setPlan).catch(() => setPlan(null));
    }, 350);
    return () => clearTimeout(t);
  }, [workspaceId, query]);

  const execute = async () => {
    if (!query.trim() || busy) return;
    abort.current?.abort();
    const ctrl = new AbortController(); abort.current = ctrl;
    setBusy(true); setError(null);
    try {
      const res = await runAgent(workspaceId, { query }, ctrl.signal);
      setRun(res); setTab("answer"); refreshMeta();
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(e instanceof ApiError ? e.message : "Agent run failed.");
    } finally { setBusy(false); }
  };

  return (
    <div className="agent-page">
      <header className="agent-header">
        <div>
          <Link to={`/workspace/${workspaceId}`} className="agent-back">← Workspace</Link>
          <h1>🤖 Agent Debug Panel</h1>
          <p className="agent-sub">Developer view of the Agent Runtime — plan, tools, execution graph, PromptPackage.</p>
        </div>
      </header>

      <div className="agent-run">
        <textarea value={query} onChange={(e) => setQuery(e.target.value)}
          placeholder="Give the agent a request… e.g. “what did the lecture say about deadlocks?” or “make flashcards”" rows={2} />
        <button onClick={execute} disabled={busy || !query.trim()}>{busy ? "Running…" : "▶ Run agent"}</button>
      </div>
      {plan && !run && (
        <div className="agent-planpreview">
          <span className="agent-tag">plan preview</span> {plan.rationale}{" "}
          <span className="agent-muted">→ {plan.graph.nodes.map((n) => n.tool).join(" · ") || "no tools"} · est. cost {plan.estimated_cost}</span>
        </div>
      )}
      {error && <div className="agent-banner">{error}</div>}

      <div className="agent-grid">
        <main className="agent-main">
          {!run && <p className="agent-empty">Run a request to inspect the execution.</p>}
          {run && (
            <>
              <div className="agent-summary">
                <span className={`agent-badge ${run.success ? "ok" : "fail"}`}>{run.phase}</span>
                <span className="agent-muted">{run.tool_count} tools · {run.retry_count} retries · {run.timings.total_ms?.toFixed(0)}ms · ~{run.token_usage} tok · cost {run.estimated_cost}</span>
              </div>
              <nav className="agent-tabs">
                {(["answer", "graph", "tools", "timeline", "prompt"] as Tab[]).map((t) => (
                  <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
                ))}
              </nav>

              {tab === "answer" && (
                <div className="agent-answer">
                  <p>{run.answer || <em className="agent-muted">no answer</em>}</p>
                  {run.citations.length > 0 && <div className="agent-muted">{run.citations.length} citation(s)</div>}
                </div>
              )}

              {tab === "graph" && (
                <div className="agent-graph">
                  <div className="agent-muted">{run.plan.planner} · {run.plan.rationale}</div>
                  {run.plan.graph.nodes.map((n) => (
                    <div key={n.id} className="agent-node">
                      <span className="agent-node-dot" style={{ background: NODE_STATUS_COLOR[n.status] || "#999" }} />
                      <span className="agent-node-tool">{n.tool}</span>
                      <span className="agent-node-status">{n.status}</span>
                      {n.depends_on.length > 0 && <span className="agent-muted">after {n.depends_on.join(", ")}</span>}
                      <span className="agent-muted">{n.latency_ms.toFixed(0)}ms · {n.attempts}x</span>
                      {n.error && <span className="agent-err">{n.error}</span>}
                    </div>
                  ))}
                </div>
              )}

              {tab === "tools" && (
                <div className="agent-toolresults">
                  {run.tool_results.map((r) => (
                    <div key={r.node} className={`agent-tr ${r.ok ? "" : "bad"}`}>
                      <div className="agent-tr-head"><b>{r.tool}</b> <span className="agent-muted">{r.latency_ms.toFixed(0)}ms · {r.citation_count} cites</span></div>
                      <pre>{r.context_preview || JSON.stringify(r.output, null, 1)}</pre>
                      {r.error && <div className="agent-err">{r.error}</div>}
                    </div>
                  ))}
                </div>
              )}

              {tab === "timeline" && (
                <ol className="agent-timeline">
                  {run.timeline.map((e) => (
                    <li key={e.seq}><span className="agent-muted">{e.at_ms.toFixed(0)}ms</span> <b>{e.event}</b> {(e.tool as string) || ""}</li>
                  ))}
                </ol>
              )}

              {tab === "prompt" && (
                <div className="agent-prompt">
                  <div className="agent-muted">{run.prompt_package.char_length} chars → single AnswerService pathway</div>
                  <pre>{run.prompt_package.rendered_preview}</pre>
                </div>
              )}
            </>
          )}
        </main>

        <aside className="agent-side">
          <section>
            <h3>Registered agents</h3>
            {agents.map((a) => (
              <div key={a.name} className="agent-desc">
                <span className={`agent-pill ${a.implemented ? "on" : "off"}`}>{a.implemented ? "live" : "planned"}</span>
                {a.name}
              </div>
            ))}
          </section>
          <section>
            <h3>Tools ({tools.length})</h3>
            {tools.map((t) => (
              <div key={t.name} className="agent-tool" title={t.description}>
                <b>{t.name}</b> <span className="agent-muted">{t.category} · {t.permissions.join("/")}</span>
              </div>
            ))}
          </section>
          <section>
            <h3>Recent executions</h3>
            {!history.length && <p className="agent-muted">none yet</p>}
            {history.slice(0, 8).map((e) => (
              <div key={e.id} className="agent-hist">
                <span className={`agent-dot ${e.success ? "ok" : "fail"}`} />
                <span className="agent-hist-q" title={e.query}>{e.query}</span>
                <span className="agent-muted">{e.total_ms.toFixed(0)}ms</span>
              </div>
            ))}
          </section>
        </aside>
      </div>
    </div>
  );
}
