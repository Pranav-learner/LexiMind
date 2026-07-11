// Vision Intelligence panel (Phase 4, Module 2) — embedded in the document detail drawer, below the
// multimodal-processing panel. Triggers vision analysis of the document's extracted visual assets and
// renders the understood knowledge: per-asset classification, semantic caption, structured metadata
// (diagram nodes / chart axes / table schema / screenshot components), confidence, keywords, and a
// thumbnail. Read-only over the async vision API; heavy VLM/CLIP work runs in a background worker.

import { useCallback, useEffect, useRef, useState } from "react";
import * as vision from "../../api/vision";
import { ApiError } from "../../api/client";
import type { VisionAnalysis, VisionJob } from "../../types";

const TYPE_ICON: Record<string, string> = {
  architecture_diagram: "🏗", flowchart: "🔀", er_diagram: "🗂", uml: "📐", network_diagram: "🕸",
  sequence_diagram: "↔", pie_chart: "🥧", bar_chart: "📊", line_chart: "📈", scatter_plot: "✴",
  area_chart: "📉", ui_screenshot: "🖥", code_screenshot: "💻", table: "▦", scientific_figure: "🔬",
  general_image: "🖼",
};

export default function VisionPanel({ workspaceId, documentId }: { workspaceId: string; documentId: string }) {
  const [job, setJob] = useState<VisionJob | null>(null);
  const [analyses, setAnalyses] = useState<VisionAnalysis[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const loadAnalyses = useCallback(async (j: VisionJob) => {
    if (j.status !== "completed") { setAnalyses([]); return; }
    try { setAnalyses((await vision.getAnalyses(workspaceId, documentId)).items); } catch { /* ignore */ }
  }, [workspaceId, documentId]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const j = await vision.getVisionStatus(workspaceId, documentId);
      setJob(j);
      if (j) await loadAnalyses(j);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load vision status.");
    } finally { setLoading(false); }
  }, [workspaceId, documentId, loadAnalyses]);

  useEffect(() => { refresh(); return () => abortRef.current?.abort(); }, [refresh]);

  const poll = useCallback((first: VisionJob) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setJob(first);
    vision.pollVision(workspaceId, documentId, { signal: controller.signal, onUpdate: setJob })
      .then((final) => { if (final) loadAnalyses(final); }).catch(() => {});
  }, [workspaceId, documentId, loadAnalyses]);

  async function analyze(force = false) {
    setBusy(true); setError(null);
    try {
      const j = await vision.analyzeDocument(workspaceId, documentId, force);
      if (j.status === "completed") { setJob(j); await loadAnalyses(j); }
      else poll(j);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start vision analysis.");
    } finally { setBusy(false); }
  }

  const running = job && (job.status === "queued" || job.status === "processing");

  return (
    <section className="mm-panel">
      <div className="mm-head">
        <h4>👁 Vision Intelligence</h4>
        {!running && (
          <button className="ws-btn primary sm" disabled={busy} onClick={() => analyze(!!job)}>
            {busy ? "Working…" : job ? "↻ Re-analyze" : "🔍 Analyze visuals"}
          </button>
        )}
      </div>

      {error && <div className="ws-error-banner sm">{error}</div>}

      {loading && !job ? (
        <p className="mm-muted">Checking status…</p>
      ) : !job ? (
        <p className="mm-muted">Understand the diagrams, charts, tables and screenshots in this document — classification, semantic captions, structured metadata, and vision embeddings.</p>
      ) : (
        <>
          <div className="mm-status-row">
            <span className={`mm-badge ${job.status}`}>{job.status === "completed" ? "Analyzed" : job.stage}</span>
            {running && (
              <>
                <div className="mm-progress"><div className="mm-progress-bar" style={{ width: `${job.progress}%` }} /></div>
                <span className="mm-muted">{job.progress}%</span>
                <button className="ws-btn ghost sm" disabled={busy} onClick={() => vision.cancelJob(workspaceId, job.id).then(refresh).catch(() => {})}>Cancel</button>
              </>
            )}
            {job.status === "failed" && (
              <button className="ws-btn ghost sm" onClick={() => vision.retryJob(workspaceId, job.id).then(poll).catch(() => {})}>🔁 Retry</button>
            )}
          </div>

          {job.status === "completed" && (
            job.asset_count === 0 ? (
              <p className="mm-muted">No visual assets found. Run multimodal processing first to extract images, tables and figures.</p>
            ) : (
              <>
                <div className="mm-classify">
                  <span className="mm-chip">{job.analyzed_count} understood</span>
                  <span className="mm-chip">{job.embedding_count} embeddings</span>
                  {job.embedding_model && <span className="mm-chip">{job.embedding_model}</span>}
                </div>
                <div className="vis-gallery">
                  {analyses.map((a) => <AnalysisCard key={a.id} ws={workspaceId} a={a} />)}
                </div>
              </>
            )
          )}
        </>
      )}
    </section>
  );
}

function AnalysisCard({ ws, a }: { ws: string; a: VisionAnalysis }) {
  const [thumb, setThumb] = useState<string | null>(null);
  useEffect(() => {
    let url: string | null = null;
    vision.fetchThumbnail(ws, a.id).then((u) => { url = u; setThumb(u); });
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [ws, a.id]);

  return (
    <div className="vis-card">
      <div className="vis-thumb">
        {thumb ? <img src={thumb} alt={a.caption} onError={(e) => (e.currentTarget.style.display = "none")} /> : null}
        <span className="vis-thumb-icon">{TYPE_ICON[a.image_type] || "🖼"}</span>
      </div>
      <div className="vis-card-body">
        <div className="vis-card-head">
          <span className="vis-type-badge">{a.image_type.replace(/_/g, " ")}</span>
          {a.confidence != null && <span className="vis-conf">{Math.round(a.confidence * 100)}%</span>}
          <span className={`vis-complexity ${a.complexity}`}>{a.complexity}</span>
        </div>
        <p className="vis-caption">{a.caption}</p>
        <Structured a={a} />
        {a.keywords && a.keywords.length > 0 && (
          <div className="vis-keywords">{a.keywords.slice(0, 6).map((k) => <span key={k} className="vis-kw">{k}</span>)}</div>
        )}
      </div>
    </div>
  );
}

function Structured({ a }: { a: VisionAnalysis }) {
  const s = a.structured as Record<string, unknown> | null;
  if (!s) return null;
  const kind = s.kind as string;
  if (kind === "diagram") {
    const nodes = (s.nodes as string[]) || [];
    return <div className="vis-structured">⛓ {nodes.slice(0, 6).join(" → ")}{nodes.length > 6 ? " …" : ""} · {String(s.edge_count ?? 0)} edges</div>;
  }
  if (kind === "chart") {
    return <div className="vis-structured">📊 {String(s.chart_type)} · x: {(s.x_axis as { label?: string })?.label} · y: {(s.y_axis as { label?: string })?.label}</div>;
  }
  if (kind === "table") {
    const cols = (s.columns as { name: string; dtype: string }[]) || [];
    return <div className="vis-structured">▦ {String(s.n_rows)}×{String(s.n_cols)} · {cols.map((c) => `${c.name}:${c.dtype}`).slice(0, 4).join(", ")}</div>;
  }
  if (kind === "screenshot") {
    return <div className="vis-structured">🖥 {((s.components as string[]) || []).join(", ")}</div>;
  }
  return null;
}
