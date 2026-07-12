// Agent Workspace (Phase 6, Module 2) — the "watch an AI researcher work" surface.
// Pick a specialized agent (Research / Write / Compare / Study), configure it, run it, and inspect the
// execution: phase timeline, evidence collected, generated outline, live output, citations, history,
// retry/cancel/export. Reuses the existing workspace shell + the /agent-tasks API.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError } from "../api/client";
import {
  AGENT_META, PHASE_COLOR, exportTaskUrl, getTask, listTasks, listWorkflows, previewTask,
  retryTask, runComparison, runResearch, runStudy, runWriting, runWorkflow,
  type TaskDetail, type TaskLog, type TaskResult, type TaskType, type WorkflowDef,
} from "../api/researchAgents";
import { API_BASE, getToken } from "../api/client";
import "../styles/agentworkspace.css";

const DOC_TYPES = [
  "research_report", "technical_report", "study_guide", "lecture_notes", "meeting_minutes",
  "design_doc", "architecture_summary", "documentation", "executive_summary", "markdown",
];
const DELIVERABLES = ["study_guide", "flashcards", "quiz", "summary", "revision", "learning_path", "weak_topics"];

type Tab = "output" | "evidence" | "plan" | "timeline" | "citations";

export default function AgentWorkspace() {
  const { workspaceId = "" } = useParams();
  const [agent, setAgent] = useState<TaskType>("research");
  const [objective, setObjective] = useState("");
  const [docIds, setDocIds] = useState("");
  const [docType, setDocType] = useState("research_report");
  const [deliverables, setDeliverables] = useState<string[]>(["study_guide", "flashcards", "learning_path"]);
  const [workflows, setWorkflows] = useState<WorkflowDef[]>([]);
  const [workflow, setWorkflow] = useState("");

  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [result, setResult] = useState<TaskResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("output");
  const [history, setHistory] = useState<TaskLog[]>([]);
  const [detail, setDetail] = useState<TaskDetail | null>(null);
  const abort = useRef<AbortController | null>(null);

  const docList = () => docIds.split(/[\s,]+/).map((d) => d.trim()).filter(Boolean);

  const refreshHistory = useCallback(async () => {
    try { setHistory(await listTasks(workspaceId)); } catch { /* ignore */ }
  }, [workspaceId]);

  useEffect(() => { refreshHistory(); }, [refreshHistory]);
  useEffect(() => {
    listWorkflows(workspaceId).then(setWorkflows).catch(() => setWorkflows([]));
  }, [workspaceId]);

  // debounced plan preview as the user types
  useEffect(() => {
    if (!objective.trim()) { setPreview(null); return; }
    const t = setTimeout(() => {
      previewTask(workspaceId, { task_type: agent, objective, document_ids: docList(),
        params: agent === "writing" ? { doc_type: docType } : agent === "study" ? { deliverables } : {} })
        .then((r) => setPreview(r.plan)).catch(() => setPreview(null));
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objective, agent, docType, deliverables, docIds, workspaceId]);

  async function run() {
    if (!objective.trim() && agent !== "study") return;
    setRunning(true); setError(""); setResult(null); setDetail(null); setTab("output");
    const ctrl = new AbortController(); abort.current = ctrl;
    try {
      let res: TaskResult;
      const ids = docList();
      if (workflow) {
        const wf = await runWorkflow(workspaceId, workflow, { objective, document_ids: ids }, ctrl.signal);
        res = wf.final as TaskResult;
      } else if (agent === "research") {
        res = await runResearch(workspaceId, { objective, document_ids: ids }, ctrl.signal);
      } else if (agent === "writing") {
        res = await runWriting(workspaceId, { objective, document_ids: ids, doc_type: docType }, ctrl.signal);
      } else if (agent === "comparison") {
        res = await runComparison(workspaceId, { objective, document_ids: ids }, ctrl.signal);
      } else {
        res = await runStudy(workspaceId, { objective: objective || "Study this workspace",
          document_ids: ids, deliverables }, ctrl.signal);
      }
      setResult(res);
      refreshHistory();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Agent task failed.");
    } finally {
      setRunning(false);
    }
  }

  async function openTask(id: string) {
    try {
      const d = await getTask(workspaceId, id);
      setDetail(d); setResult(null); setTab("output");
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not load task."); }
  }

  async function doRetry(id: string) {
    setRunning(true);
    try { setResult(await retryTask(workspaceId, id)); setDetail(null); refreshHistory(); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Retry failed."); }
    finally { setRunning(false); }
  }

  function downloadExport(id: string, fmt: "markdown" | "json") {
    const token = getToken();
    fetch(API_BASE + exportTaskUrl(workspaceId, id, fmt), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).then((r) => r.json()).then((data) => {
      const content = fmt === "json" ? JSON.stringify(data.content, null, 2) : String(data.content);
      const blob = new Blob([content], { type: "text/plain" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = data.filename || `task.${fmt === "json" ? "json" : "md"}`;
      a.click(); URL.revokeObjectURL(a.href);
    }).catch(() => setError("Export failed."));
  }

  const active = detail ?? result;
  const activeId = active ? ((active as TaskResult).task_id ?? (active as TaskDetail).id) : "";
  const out = active?.output ?? null;
  const steps = active?.steps ?? [];
  const evidence = result?.evidence ?? [];
  const plan = active?.plan ?? preview;
  const citations = out?.citations ?? [];

  return (
    <div className="aw-page">
      <header className="aw-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🧑‍🔬 Agent Workspace</h1>
        <Link to={`/workspace/${workspaceId}/agent`} className="aw-muted">Runtime debug →</Link>
      </header>

      <div className="aw-grid">
        {/* ---------------- configure + run ---------------- */}
        <section className="aw-config">
          <div className="aw-agent-picker">
            {(Object.keys(AGENT_META) as TaskType[]).map((a) => (
              <button key={a} className={`aw-agent-card ${agent === a && !workflow ? "is-active" : ""}`}
                onClick={() => { setAgent(a); setWorkflow(""); }}>
                <span className="aw-agent-icon">{AGENT_META[a].icon}</span>
                <span className="aw-agent-label">{AGENT_META[a].label}</span>
                <span className="aw-agent-blurb">{AGENT_META[a].blurb}</span>
              </button>
            ))}
          </div>

          <label className="aw-field">
            <span>Objective</span>
            <textarea rows={3} value={objective} placeholder="e.g. Compare deadlock prevention strategies across the lectures"
              onChange={(e) => setObjective(e.target.value)} />
          </label>

          <label className="aw-field">
            <span>Document scope <em>(optional — ids, comma/space separated; blank = whole workspace)</em></span>
            <input value={docIds} onChange={(e) => setDocIds(e.target.value)} placeholder="doc_… doc_…" />
          </label>

          {agent === "writing" && !workflow && (
            <label className="aw-field">
              <span>Document type</span>
              <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                {DOC_TYPES.map((d) => <option key={d} value={d}>{d.replace(/_/g, " ")}</option>)}
              </select>
            </label>
          )}

          {agent === "study" && !workflow && (
            <div className="aw-field">
              <span>Deliverables</span>
              <div className="aw-chips">
                {DELIVERABLES.map((d) => (
                  <button key={d} type="button"
                    className={`aw-chip ${deliverables.includes(d) ? "is-on" : ""}`}
                    onClick={() => setDeliverables((cur) =>
                      cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d])}>
                    {d.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            </div>
          )}

          <label className="aw-field">
            <span>Or run a workflow</span>
            <select value={workflow} onChange={(e) => setWorkflow(e.target.value)}>
              <option value="">— single agent —</option>
              {workflows.map((w) => <option key={w.name} value={w.name}>{w.name.replace(/_/g, " ")}</option>)}
            </select>
          </label>

          <div className="aw-run-row">
            <button className="aw-run" disabled={running} onClick={run}>
              {running ? "Working…" : workflow ? "Run workflow" : `Run ${AGENT_META[agent].label}`}
            </button>
          </div>
          {error && <p className="aw-error">{error}</p>}

          {plan && (
            <div className="aw-plan-preview">
              <h4>Plan</h4>
              <pre>{JSON.stringify(plan, null, 2)}</pre>
            </div>
          )}
        </section>

        {/* ---------------- results ---------------- */}
        <main className="aw-main">
          {!active && !running && <div className="aw-empty">Configure an agent and press run to watch it work.</div>}
          {running && <div className="aw-empty">The agent is planning, researching and writing…</div>}

          {active && (
            <>
              <div className="aw-result-head">
                <div>
                  <h2>{out?.title || active.objective}</h2>
                  <p className="aw-muted">{out?.summary}</p>
                </div>
                <div className="aw-result-actions">
                  <span className="aw-phase" style={{ background: PHASE_COLOR[active.phase] || "#64748b" }}>
                    {active.phase}
                  </span>
                  <button onClick={() => downloadExport(activeId, "markdown")}>Export .md</button>
                  <button onClick={() => downloadExport(activeId, "json")}>.json</button>
                  <button onClick={() => doRetry(activeId)}>Retry</button>
                </div>
              </div>

              {/* phase pipeline */}
              <div className="aw-steps">
                {steps.map((s, i) => (
                  <div className="aw-step" key={i}>
                    <span className="aw-step-dot" style={{ background: PHASE_COLOR[s.phase] || "#94a3b8" }} />
                    <span className="aw-step-label">{s.label}</span>
                    <span className="aw-step-detail">{s.detail}</span>
                    <span className="aw-step-ms">{Math.round(s.ms)}ms</span>
                  </div>
                ))}
              </div>

              <nav className="aw-tabs">
                {(["output", "evidence", "plan", "timeline", "citations"] as Tab[]).map((t) => (
                  <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
                ))}
              </nav>

              {tab === "output" && (
                <article className="aw-output">
                  {out?.markdown
                    ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{out.markdown}</ReactMarkdown>
                    : <em>No output.</em>}
                </article>
              )}

              {tab === "evidence" && (
                <ul className="aw-evidence">
                  {evidence.length === 0 && <li className="aw-muted">No structured evidence captured for this view.</li>}
                  {evidence.map((e, i) => (
                    <li key={i}>
                      <span className="aw-ev-idx">[{e.index}]</span>
                      <span className="aw-ev-text">{e.text}</span>
                      <span className="aw-ev-meta">
                        {e.origin_tool}{e.timespan ? ` · ${e.timespan}` : ""}
                        {e.page_number != null ? ` · p${e.page_number}` : ""} · {e.score.toFixed(2)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {tab === "plan" && <pre className="aw-json">{JSON.stringify(active.plan, null, 2)}</pre>}

              {tab === "timeline" && (
                <ol className="aw-timeline">
                  {((active.timeline as Record<string, unknown>[]) ?? []).map((ev, i) => (
                    <li key={i}><b>{String(ev.event)}</b> <span className="aw-muted">{String(ev.at_ms)}ms</span></li>
                  ))}
                </ol>
              )}

              {tab === "citations" && (
                <ul className="aw-citations">
                  {citations.length === 0 && <li className="aw-muted">No citations.</li>}
                  {citations.map((c, i) => (
                    <li key={i}><b>[{String(c.index ?? i + 1)}]</b> {String(c.title ?? c.document_id ?? "source")}
                      {c.text ? ` — ${String(c.text).slice(0, 160)}` : ""}</li>
                  ))}
                </ul>
              )}
            </>
          )}
        </main>

        {/* ---------------- history ---------------- */}
        <aside className="aw-side">
          <h3>History</h3>
          <ul className="aw-history">
            {history.length === 0 && <li className="aw-muted">No tasks yet.</li>}
            {history.map((t) => (
              <li key={t.id} onClick={() => openTask(t.id)}>
                <span className="aw-hist-type">{AGENT_META[t.task_type as TaskType]?.icon ?? "•"} {t.task_type}</span>
                <span className="aw-hist-obj">{t.objective.slice(0, 48)}</span>
                <span className={`aw-hist-status s-${t.status}`}>{t.status}</span>
                {t.workflow && <span className="aw-hist-wf">{t.workflow}</span>}
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}
