// Continuous Learning Workspace (Phase 8, Module 4) — the improvement control room.
// Feedback dashboard · failure clusters · governed recommendation review queue (approve/reject) ·
// dataset generation · improvement history. Nothing is auto-applied — every rec is a human decision.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  STATUS_COLOR, SEVERITY_COLOR, approve, buildDataset, catLabel, categoryColor,
  dashboard as fetchDashboard, recommendations as fetchRecs, reject, runCycle,
  type Dashboard, type Recommendation,
} from "../api/learning";
import "../styles/learning.css";

type Tab = "insights" | "review" | "feedback" | "history";

export default function LearningWorkspace() {
  const { workspaceId = "" } = useParams();
  const [tab, setTab] = useState<Tab>("insights");
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [recStatus, setRecStatus] = useState("pending");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try { setDash(await fetchDashboard(workspaceId)); } catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load."); }
  }, [workspaceId]);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { if (tab === "review") fetchRecs(workspaceId, recStatus).then(setRecs).catch(() => {}); }, [tab, recStatus, workspaceId]);

  async function cycle() {
    setBusy(true); setError("");
    try { await runCycle(workspaceId); refresh(); if (tab === "review") setRecs(await fetchRecs(workspaceId, recStatus)); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Cycle failed."); }
    finally { setBusy(false); }
  }
  async function decide(id: string, action: "approve" | "reject") {
    try {
      await (action === "approve" ? approve : reject)(workspaceId, id, note);
      setNote(""); setRecs(await fetchRecs(workspaceId, recStatus)); refresh();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Review failed."); }
  }
  async function makeDataset() {
    try { const r = await buildDataset(workspaceId); setError(r.created ? `Created dataset "${r.name}" (${r.item_count} items)` : `No dataset: ${r.reason}`); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Failed."); }
  }

  const fb = dash?.feedback;

  return (
    <div className="cl-page">
      <header className="cl-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🔁 Continuous Learning</h1>
        <div className="cl-actions">
          <button onClick={makeDataset}>＋ Failure dataset</button>
          <button className="cl-primary" disabled={busy} onClick={cycle}>{busy ? "Learning…" : "Run learning cycle"}</button>
        </div>
      </header>
      {error && <p className="cl-error" onClick={() => setError("")}>{error} ✕</p>}

      {dash && fb && (
        <div className="cl-stat-row">
          <Stat label="Feedback" v={fb.total} />
          <Stat label="Negative rate" v={`${Math.round(fb.negative_rate * 100)}%`} color={fb.negative_rate > 0.3 ? "#ef4444" : undefined} />
          <Stat label="Corrections" v={fb.corrections} />
          <Stat label="Failures" v={dash.insights.total_failures} />
          <Stat label="Pending recs" v={dash.review.pending} color={dash.review.pending ? "#f59e0b" : undefined} />
          <Stat label="Approved" v={dash.review.approved} color="#10b981" />
        </div>
      )}

      <nav className="cl-tabs">
        {(["insights", "review", "feedback", "history"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "is-active" : ""} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>

      {tab === "insights" && dash && (
        <div className="cl-cols">
          <div>
            <h4>Failure categories</h4>
            {Object.entries(dash.insights.by_category).sort(([, a], [, b]) => b - a).map(([c, n]) => (
              <div className="cl-bar-row" key={c}>
                <span className="cl-bar-label">{catLabel(c)}</span>
                <div className="cl-bar"><div style={{ width: `${Math.min(100, n * 20)}%`, background: "#6366f1" }} /></div>
                <span className="cl-bar-n">{n}</span>
              </div>
            ))}
            {Object.keys(dash.insights.by_category).length === 0 && <p className="cl-muted">No failures detected. 🎉</p>}
          </div>
          <div>
            <h4>Failure clusters</h4>
            {dash.insights.clusters.map((cl) => (
              <div className="cl-cluster" key={cl.cluster_id} style={{ borderLeftColor: SEVERITY_COLOR[cl.severity] }}>
                <div className="cl-cluster-head">
                  <b>{catLabel(cl.category)}</b>
                  <span className="cl-cluster-count">×{cl.count}</span>
                  <span className="cl-sev" style={{ color: SEVERITY_COLOR[cl.severity] }}>{cl.severity}</span>
                </div>
                {cl.sample_details.map((d, i) => <p className="cl-sample" key={i}>{d}</p>)}
              </div>
            ))}
            {dash.insights.clusters.length === 0 && <p className="cl-muted">No clusters.</p>}
          </div>
        </div>
      )}

      {tab === "review" && (
        <div className="cl-review">
          <div className="cl-review-bar">
            {["pending", "approved", "rejected"].map((s) => (
              <button key={s} className={recStatus === s ? "is-active" : ""} onClick={() => setRecStatus(s)}>{s}</button>
            ))}
            {recStatus === "pending" && recs.length > 0 && (
              <input className="cl-note" placeholder="review note (optional)…" value={note} onChange={(e) => setNote(e.target.value)} />
            )}
          </div>
          {recs.map((r) => (
            <div className="cl-rec" key={r.id} style={{ borderLeftColor: categoryColor(r.category) }}>
              <div className="cl-rec-head">
                <span className="cl-cat" style={{ background: categoryColor(r.category) }}>{r.category}</span>
                <b>{r.title}</b>
                <span className="cl-conf">conf {Math.round(r.confidence * 100)}%</span>
                <span className="cl-status" style={{ color: STATUS_COLOR[r.status] }}>{r.status}</span>
              </div>
              <p className="cl-reason"><b>Why:</b> {r.reason}</p>
              <p className="cl-impact"><b>Expected impact:</b> {r.expected_impact}</p>
              <div className="cl-components">{r.affected_components.map((c) => <span key={c}>{c}</span>)}</div>
              {r.status === "pending" && (
                <div className="cl-decide">
                  <button className="cl-approve" onClick={() => decide(r.id, "approve")}>✓ Approve</button>
                  <button className="cl-reject" onClick={() => decide(r.id, "reject")}>✕ Reject</button>
                </div>
              )}
              {r.reviewed_at && <p className="cl-reviewed">reviewed by {r.reviewer} · {r.review_note}</p>}
            </div>
          ))}
          {recs.length === 0 && <p className="cl-muted">No {recStatus} recommendations. Run a learning cycle to generate some.</p>}
        </div>
      )}

      {tab === "feedback" && dash && fb && (
        <div className="cl-cols">
          <div>
            <h4>By sentiment</h4>
            {Object.entries(fb.by_sentiment).map(([s, n]) => (
              <div className="cl-kv" key={s}><span>{s}</span><b>{n}</b></div>
            ))}
            <h4>By target</h4>
            {Object.entries(fb.by_target).map(([t, n]) => (
              <div className="cl-kv" key={t}><span>{t}</span><b>{n}</b></div>
            ))}
          </div>
          <div>
            <h4>By kind</h4>
            {Object.entries(fb.by_kind).map(([k, n]) => (
              <div className="cl-kv" key={k}><span>{k}</span><b>{n}</b></div>
            ))}
            <div className="cl-kv"><span>avg rating</span><b>{fb.avg_rating ?? "—"}</b></div>
          </div>
        </div>
      )}

      {tab === "history" && dash && (
        <table className="cl-table">
          <thead><tr><th>Cycle</th><th>Failures</th><th>Clusters</th><th>Recs</th><th>Confidence</th><th>Components</th><th>When</th></tr></thead>
          <tbody>
            {dash.review.cycles.map((c) => (
              <tr key={c.id}>
                <td>{c.id.slice(0, 10)}</td><td>{c.failures_analyzed}</td><td>{c.clusters}</td>
                <td>{c.recommendations_generated}</td><td>{Math.round(c.avg_confidence * 100)}%</td>
                <td className="cl-comp-cell">{c.affected_components.join(", ")}</td>
                <td>{c.created_at ? new Date(c.created_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
            {dash.review.cycles.length === 0 && <tr><td colSpan={7} className="cl-muted">No learning cycles yet.</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Stat({ label, v, color }: { label: string; v: number | string; color?: string }) {
  return <div className="cl-stat"><span className="cl-stat-v" style={color ? { color } : undefined}>{v}</span><span className="cl-stat-l">{label}</span></div>;
}
