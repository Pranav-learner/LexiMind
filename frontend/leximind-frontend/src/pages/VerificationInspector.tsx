// Verification Inspector (Phase 6, Module 3) — a developer/debug surface over the trust layer.
// Lists recent verifications for the workspace + renders the selected report via VerificationPanel.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/client";
import {
  STATUS_META, confidenceColor, getVerification, getTaskVerification, listVerifications,
  verificationStats, type VerificationDetail, type VerificationLog,
} from "../api/verification";
import VerificationPanel from "../components/verification/VerificationPanel";
import "../styles/verification.css";

export default function VerificationInspector() {
  const { workspaceId = "" } = useParams();
  const [params] = useSearchParams();
  const [logs, setLogs] = useState<VerificationLog[]>([]);
  const [selected, setSelected] = useState<VerificationDetail | null>(null);
  const [stats, setStats] = useState<{ verifications: number; verified: number; failed: number; avg_confidence: number } | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setLogs(await listVerifications(workspaceId));
      setStats(await verificationStats(workspaceId));
    } catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load verifications."); }
  }, [workspaceId]);

  useEffect(() => { refresh(); }, [refresh]);

  // deep-link: ?task=<id> loads a task's verification
  useEffect(() => {
    const task = params.get("task");
    if (task) getTaskVerification(workspaceId, task).then(setSelected).catch(() => { /* none yet */ });
  }, [params, workspaceId]);

  async function open(id: string) {
    try { setSelected(await getVerification(workspaceId, id)); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Failed to load report."); }
  }

  return (
    <div className="vfi-page">
      <header className="vfi-header">
        <Link to={`/workspace/${workspaceId}`}>← Workspace</Link>
        <h1>🛡️ Verification Inspector</h1>
        <Link to={`/workspace/${workspaceId}/agents`} className="vfi-muted">Agent Workspace →</Link>
      </header>

      {stats && (
        <div className="vfi-stats">
          <span><b>{stats.verifications}</b> verifications</span>
          <span style={{ color: "#10b981" }}><b>{stats.verified}</b> verified</span>
          <span style={{ color: "#ef4444" }}><b>{stats.failed}</b> failed</span>
          <span style={{ color: confidenceColor(stats.avg_confidence) }}>
            avg confidence <b>{Math.round(stats.avg_confidence * 100)}%</b></span>
        </div>
      )}
      {error && <p className="vfi-error">{error}</p>}

      <div className="vfi-grid">
        <aside className="vfi-list">
          {logs.length === 0 && <p className="vfi-muted">No verifications yet. Run an agent task or use the Verify API.</p>}
          {logs.map((l) => {
            const meta = STATUS_META[l.status] ?? STATUS_META.warning;
            return (
              <button key={l.id} className={`vfi-item ${selected?.id === l.id ? "is-active" : ""}`} onClick={() => open(l.id)}>
                <span className="vfi-item-status" style={{ background: meta.color }}>{meta.icon}</span>
                <span className="vfi-item-main">
                  <span className="vfi-item-agent">{l.agent || "ad-hoc"} · {l.task_type || "verify"}</span>
                  <span className="vfi-item-sub">
                    {l.claims_total} claims · {l.contradictions_found} contradictions · {Math.round(l.overall_confidence * 100)}%
                  </span>
                </span>
              </button>
            );
          })}
        </aside>

        <main className="vfi-main">
          {selected?.report
            ? <VerificationPanel report={selected.report} />
            : <div className="vfi-empty">Select a verification to inspect its evidence, claims, contradictions and confidence.</div>}
        </main>
      </div>
    </div>
  );
}
