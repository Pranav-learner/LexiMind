// Multimodal processing panel (Phase 4, Module 1) — embedded in the document detail drawer.
//
// Shows the multimodal-ingestion job for a document: a Process/Reprocess button, live stage +
// progress while running (polled to a terminal state), the classification, OCR / image / table /
// figure / chunk counts, an extracted-asset viewer, processing logs, and retry/cancel. Everything
// is read-only over the async ingestion API; the heavy OCR/vision work runs in a background worker.

import { useCallback, useEffect, useRef, useState } from "react";
import * as ing from "../../api/ingestion";
import { ApiError } from "../../api/client";
import type { ExtractedAssets, OcrStatus, ProcessingJob } from "../../types";

const STAGE_LABEL: Record<string, string> = {
  queued: "Queued", validating: "Validating", classification: "Classifying", ocr: "Running OCR",
  extraction: "Extracting assets", chunking: "Building chunks", completed: "Completed",
  failed: "Failed", cancelled: "Cancelled",
};

export default function ProcessingPanel({ workspaceId, documentId }: { workspaceId: string; documentId: string }) {
  const [job, setJob] = useState<ProcessingJob | null>(null);
  const [assets, setAssets] = useState<ExtractedAssets | null>(null);
  const [ocr, setOcr] = useState<OcrStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const [logs, setLogs] = useState<{ stage: string; level: string; message: string }[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const loadResults = useCallback(async (j: ProcessingJob) => {
    if (j.status !== "completed") { setAssets(null); setOcr(null); return; }
    try {
      const [a, o] = await Promise.all([ing.getAssets(workspaceId, documentId), ing.getOcr(workspaceId, documentId)]);
      setAssets(a); setOcr(o);
    } catch { /* ignore */ }
  }, [workspaceId, documentId]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const j = await ing.getProcessingStatus(workspaceId, documentId);
      setJob(j);
      if (j) await loadResults(j);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load processing status.");
    } finally { setLoading(false); }
  }, [workspaceId, documentId, loadResults]);

  useEffect(() => { refresh(); return () => abortRef.current?.abort(); }, [refresh]);

  const poll = useCallback((first: ProcessingJob) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setJob(first);
    ing.pollProcessing(workspaceId, documentId, {
      signal: controller.signal,
      onUpdate: (j) => setJob(j),
    }).then((final) => { if (final) loadResults(final); }).catch(() => {});
  }, [workspaceId, documentId, loadResults]);

  async function process(force = false) {
    setBusy(true); setError(null);
    try {
      const j = await ing.processDocument(workspaceId, documentId, force);
      if (j.status === "completed") { setJob(j); await loadResults(j); }
      else poll(j);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start processing.");
    } finally { setBusy(false); }
  }

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); await refresh(); } catch (err) { setError(err instanceof ApiError ? err.message : "Action failed."); }
    finally { setBusy(false); }
  }

  async function toggleLogs() {
    const next = !showLogs;
    setShowLogs(next);
    if (next && job) {
      try { setLogs((await ing.getJobDetail(workspaceId, job.id)).logs); } catch { /* ignore */ }
    }
  }

  const running = job && (job.status === "queued" || job.status === "processing");

  return (
    <section className="mm-panel">
      <div className="mm-head">
        <h4>🧩 Multimodal Processing</h4>
        {!running && (
          <button className="ws-btn primary sm" disabled={busy} onClick={() => process(!!job)}>
            {busy ? "Working…" : job ? "↻ Reprocess" : "⚙ Process document"}
          </button>
        )}
      </div>

      {error && <div className="ws-error-banner sm">{error}</div>}

      {loading && !job ? (
        <p className="mm-muted">Checking status…</p>
      ) : !job ? (
        <p className="mm-muted">Run multimodal processing to extract OCR text, images, tables and figures — the foundation for future vision & cross-modal retrieval.</p>
      ) : (
        <>
          <div className="mm-status-row">
            <span className={`mm-badge ${job.status}`}>{STAGE_LABEL[job.stage] || job.stage}</span>
            {running && (
              <>
                <div className="mm-progress"><div className="mm-progress-bar" style={{ width: `${job.progress}%` }} /></div>
                <span className="mm-muted">{job.progress}%</span>
                <button className="ws-btn ghost sm" disabled={busy} onClick={() => act(() => ing.cancelJob(workspaceId, job.id))}>Cancel</button>
              </>
            )}
            {job.status === "failed" && (
              <button className="ws-btn ghost sm" disabled={busy} onClick={() => act(async () => { const j = await ing.retryJob(workspaceId, job.id); poll(j); })}>🔁 Retry</button>
            )}
          </div>

          {job.error && <div className="ws-error-banner sm">{job.error}</div>}

          {job.status === "completed" && (
            <>
              <div className="mm-classify">
                <span className="mm-chip">{job.doc_type.replace("_", " ")}</span>
                <span className="mm-chip">{job.processing_type}</span>
                {job.ocr_language && <span className="mm-chip">lang: {job.ocr_language}</span>}
                {job.processing_ms > 0 && <span className="mm-chip">⏱ {(job.processing_ms / 1000).toFixed(1)}s</span>}
              </div>

              <div className="mm-counts">
                <Count icon="📄" value={job.ocr_pages} label="OCR pages" />
                <Count icon="🖼" value={job.image_count} label="Images" />
                <Count icon="▦" value={job.table_count} label="Tables" />
                <Count icon="📊" value={job.figure_count} label="Figures" />
                <Count icon="🧩" value={job.chunk_count} label="Chunks" />
                {job.ocr_confidence != null && <Count icon="🎯" value={`${Math.round(job.ocr_confidence * 100)}%`} label="OCR conf." />}
              </div>

              {assets && (assets.images.length + assets.tables.length + assets.figures.length > 0) && (
                <div className="mm-assets">
                  {assets.tables.map((t) => (
                    <div key={t.id} className="mm-asset">
                      <span className="mm-asset-head">▦ Table · p.{t.page_number} · {t.n_rows}×{t.n_cols}</span>
                      {t.headers && <div className="mm-table-headers">{(t.headers as string[]).join(" · ")}</div>}
                    </div>
                  ))}
                  {assets.figures.map((f) => (
                    <div key={f.id} className="mm-asset">
                      <span className="mm-asset-head">📊 {f.figure_type} · p.{f.page_number}</span>
                      {f.caption && <div className="mm-asset-cap">{f.caption}</div>}
                    </div>
                  ))}
                  {assets.images.map((im) => (
                    <div key={im.id} className="mm-asset">
                      <span className="mm-asset-head">🖼 {im.image_type} · p.{im.page_number}{im.width ? ` · ${im.width}×${im.height}` : ""}</span>
                    </div>
                  ))}
                </div>
              )}

              {ocr && ocr.pages.length > 0 && (
                <details className="mm-ocr">
                  <summary>OCR text ({ocr.ocr_pages} pages)</summary>
                  {ocr.pages.slice(0, 5).map((p) => (
                    <div key={p.page_number} className="mm-ocr-page"><strong>p.{p.page_number}</strong> {p.text.slice(0, 200)}</div>
                  ))}
                </details>
              )}
            </>
          )}

          <button className="mm-logs-toggle" onClick={toggleLogs}>{showLogs ? "▾" : "▸"} Processing logs</button>
          {showLogs && (
            <div className="mm-logs">
              {logs.length === 0 ? <span className="mm-muted">No logs.</span> : logs.map((l, i) => (
                <div key={i} className={`mm-log lvl-${l.level}`}><span className="mm-log-stage">{l.stage}</span> {l.message}</div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Count({ icon, value, label }: { icon: string; value: number | string; label: string }) {
  return (
    <div className="mm-count">
      <span className="mm-count-icon" aria-hidden="true">{icon}</span>
      <span className="mm-count-value">{value}</span>
      <span className="mm-count-label">{label}</span>
    </div>
  );
}
