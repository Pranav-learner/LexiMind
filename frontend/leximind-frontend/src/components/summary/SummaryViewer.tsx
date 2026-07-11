// Renders a SummaryDetail: a header (title + inline rename + type/status/generation-time meta),
// then each section (heading + Markdown body via react-markdown/remark-gfm/rehype-highlight) with
// its citation cards below. While the summary is still generating (queued/processing) it shows a
// live progress view — polling GET /{id}/status, a progress bar + stage, and a Cancel button —
// then auto-refreshes into the finished view. Actions: Copy all, Export (.md), Print, Regenerate,
// Duplicate, Delete. Citation clicks are resolved by the parent (vector id → PDF viewer).
//
// Owns its own fetch + polling lifecycle; a single AbortController tears both down on unmount or
// when the summary id / reload key changes.

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import * as summaryApi from "../../api/summaries";
import { noteFromSummary } from "../../api/notes";
import { isTerminal } from "../../api/summaries";
import { ApiError } from "../../api/client";
import type {
  Summary,
  SummaryCitation,
  SummaryDetail,
  SummarySectionT,
} from "../../types";
import {
  SCOPE_META,
  STATUS_META,
  relativeTime,
  summaryTypeIcon,
  summaryTypeLabel,
} from "./constants";

interface Props {
  ws: string;
  summaryId: string;
  onCitation: (c: SummaryCitation) => void;
  onChanged: () => void; // refresh the dashboard list
  onDeleted: () => void; // navigate away after a delete
  onOpenSummary: (id: string) => void; // open a different summary (e.g. after duplicate)
}

export default function SummaryViewer({
  ws,
  summaryId,
  onCitation,
  onChanged,
  onDeleted,
  onOpenSummary,
}: Props) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<SummaryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  // Keep callback identities out of the fetch effect's dependency list.
  const onChangedRef = useRef(onChanged);
  useEffect(() => { onChangedRef.current = onChanged; });

  // Fetch detail, then poll to a terminal state if the summary is still generating.
  useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const d = await summaryApi.getSummary(ws, summaryId, controller.signal);
        if (!alive) return;
        setDetail(d);
        setLoading(false);

        if (!isTerminal(d.status)) {
          await summaryApi.pollSummaryStatus(ws, summaryId, {
            signal: controller.signal,
            onUpdate: (s: Summary) =>
              alive && setDetail((prev) => (prev ? { ...prev, ...s } : prev)),
          });
          if (!alive) return;
          // Terminal reached — refetch full detail (sections now available) and refresh the list.
          const full = await summaryApi.getSummary(ws, summaryId, controller.signal);
          if (!alive) return;
          setDetail(full);
          onChangedRef.current();
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (!alive) return;
        setError(err instanceof ApiError ? err.message : "Failed to load summary.");
        setLoading(false);
      }
    })();

    return () => {
      alive = false;
      controller.abort();
    };
  }, [ws, summaryId, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  async function saveTitle() {
    const next = titleDraft.trim();
    setEditingTitle(false);
    if (!detail || !next || next === detail.title) return;
    try {
      const updated = await summaryApi.renameSummary(ws, summaryId, next);
      setDetail((prev) => (prev ? { ...prev, ...updated } : prev));
      onChangedRef.current();
    } catch {
      /* ignore */
    }
  }

  async function act(fn: () => Promise<unknown>, after?: () => void) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      after?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  function handleRegenerate() {
    act(
      () => summaryApi.regenerateSummary(ws, summaryId),
      () => {
        onChangedRef.current();
        reload(); // re-fetch + resume polling for the new run
      },
    );
  }

  function handleCancel() {
    act(
      () => summaryApi.cancelSummary(ws, summaryId),
      () => {
        // The in-flight poll will observe the cancelled state and stop on its own.
        setDetail((prev) => (prev ? { ...prev, status: "cancelled" } : prev));
        onChangedRef.current();
      },
    );
  }

  async function handleDuplicate() {
    setBusy(true);
    setError(null);
    try {
      // Duplicate returns the new SummaryDetail; open it once created.
      const copy = await summaryApi.duplicateSummary(ws, summaryId);
      onChangedRef.current();
      onOpenSummary(copy.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  function handleDelete() {
    if (!window.confirm("Delete this summary? It will be moved to trash (soft delete).")) return;
    act(
      () => summaryApi.deleteSummary(ws, summaryId),
      () => {
        onChangedRef.current();
        onDeleted();
      },
    );
  }

  function copyAll() {
    if (!detail) return;
    const text = detail.sections
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((s) => `## ${s.heading}\n\n${s.content}`)
      .join("\n\n");
    navigator.clipboard?.writeText(`# ${detail.title}\n\n${text}`);
  }

  function handleExport() {
    if (!detail) return;
    const safe = (detail.title || "summary").replace(/[^\w.-]+/g, "_").slice(0, 80);
    summaryApi.exportSummary(ws, summaryId, `${safe}.md`).catch(() => {});
  }

  // Module 6: convert this summary into an editable Note (sections + citations preserved).
  async function handleConvertToNotes() {
    setBusy(true);
    setError(null);
    try {
      const note = await noteFromSummary(ws, summaryId);
      navigate(`/workspace/${ws}/notes/${note.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not convert to notes.");
    } finally {
      setBusy(false);
    }
  }

  if (loading && !detail) {
    return (
      <div className="sum-viewer sum-viewer-status">
        <span className="ws-brand-mark spin">🧠</span>
        <p>Loading summary…</p>
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="sum-viewer sum-viewer-status">
        <div className="ws-error-banner">{error}</div>
        <button className="ws-btn ghost" onClick={reload}>Retry</button>
      </div>
    );
  }

  if (!detail) return null;

  const status = STATUS_META[detail.status];
  const scope = SCOPE_META[detail.scope];
  const generating = detail.status === "queued" || detail.status === "processing";
  const failed = detail.status === "failed";
  const sections = detail.sections
    ? [...detail.sections].sort((a, b) => a.order - b.order)
    : [];

  return (
    <div className="sum-viewer">
      <header className="sum-viewer-header">
        <div className="sum-viewer-title">
          {editingTitle ? (
            <input
              className="sum-title-edit"
              value={titleDraft}
              autoFocus
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={saveTitle}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveTitle();
                else if (e.key === "Escape") setEditingTitle(false);
              }}
              aria-label="Summary title"
            />
          ) : (
            <button
              className="sum-title-btn"
              title="Rename summary"
              onClick={() => {
                setTitleDraft(detail.title);
                setEditingTitle(true);
              }}
            >
              {detail.title || "Untitled summary"}{" "}
              <span className="sum-title-edit-icon" aria-hidden="true">✏️</span>
            </button>
          )}
          <div className="sum-viewer-meta">
            <span className="sum-type-badge">
              <span aria-hidden="true">{summaryTypeIcon(detail.summary_type)}</span>
              {summaryTypeLabel(detail.summary_type)}
            </span>
            <span className={`sum-status ${status.tone}`}>{status.label}</span>
            <span className="sum-meta-item" title={scope.label}>{scope.icon} {scope.label}</span>
            {detail.generation_ms != null && detail.status === "completed" && (
              <span className="sum-meta-item">⏱ {(detail.generation_ms / 1000).toFixed(1)}s</span>
            )}
            {detail.model_name && <span className="sum-meta-item">{detail.model_name}</span>}
            <span className="sum-meta-item">Updated {relativeTime(detail.updated_at)}</span>
          </div>
        </div>

        <div className="sum-actions" onClick={(e) => e.stopPropagation()}>
          <button className="ws-btn ghost" onClick={copyAll} disabled={generating} title="Copy all">📋 Copy</button>
          <button className="ws-btn ghost" onClick={handleExport} disabled={generating} title="Export as Markdown">⬇ Export</button>
          <button className="ws-btn ghost" onClick={handleConvertToNotes} disabled={busy || generating} title="Convert to editable notes">📝 To notes</button>
          <button className="ws-btn ghost" onClick={() => window.print()} disabled={generating} title="Print">🖨 Print</button>
          <button className="ws-btn ghost" onClick={handleRegenerate} disabled={busy || generating} title="Regenerate">🔄 Regenerate</button>
          <button className="ws-btn ghost" onClick={handleDuplicate} disabled={busy} title="Duplicate">📑 Duplicate</button>
          <button className="ws-btn ghost doc-danger-btn" onClick={handleDelete} disabled={busy} title="Delete">🗑️ Delete</button>
        </div>
      </header>

      {error && <div className="ws-error-banner">{error}</div>}

      {generating ? (
        <div className="sum-generating">
          <span className="ws-brand-mark spin">🧠</span>
          <h3>Generating your summary…</h3>
          <div className="sum-progress big" aria-label={`${detail.progress}% generated`}>
            <div className="sum-progress-bar" style={{ width: `${detail.progress}%` }} />
          </div>
          <p className="sum-stage">{detail.stage || "Working…"} · {detail.progress}%</p>
          <button className="ws-btn ghost" onClick={handleCancel} disabled={busy}>
            ✕ Cancel generation
          </button>
        </div>
      ) : failed ? (
        <div className="sum-generating sum-failed">
          <div className="ws-empty-mark">⚠️</div>
          <h3>Generation failed</h3>
          <p className="sum-error-text">{detail.error || "Something went wrong."}</p>
          <button className="ws-btn primary" onClick={handleRegenerate} disabled={busy}>
            🔄 Regenerate
          </button>
        </div>
      ) : detail.status === "cancelled" ? (
        <div className="sum-generating">
          <div className="ws-empty-mark">🚫</div>
          <h3>Generation cancelled</h3>
          <button className="ws-btn primary" onClick={handleRegenerate} disabled={busy}>
            🔄 Regenerate
          </button>
        </div>
      ) : sections.length === 0 ? (
        <div className="sum-generating">
          <div className="ws-empty-mark">📄</div>
          <p>This summary has no content.</p>
        </div>
      ) : (
        <div className="sum-sections">
          {sections.map((section) => (
            <Section key={section.id} section={section} onCitation={onCitation} />
          ))}
        </div>
      )}
    </div>
  );
}

function Section({
  section,
  onCitation,
}: {
  section: SummarySectionT;
  onCitation: (c: SummaryCitation) => void;
}) {
  return (
    <section className="sum-section">
      {section.heading && <h2 className="sum-section-heading">{section.heading}</h2>}
      <div className="chat-markdown sum-section-body">
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
          {section.content}
        </ReactMarkdown>
      </div>
      {section.citations && section.citations.length > 0 && (
        <div className="chat-citations sum-citations">
          {section.citations.map((c, i) => (
            <CitationButton key={c.id || i} citation={c} index={i} onClick={onCitation} />
          ))}
        </div>
      )}
    </section>
  );
}

// Mirrors the chat CitationCard markup (reusing its chat-citation* styles) but typed for a
// SummaryCitation so citation navigation flows through the summary handler.
function CitationButton({
  citation,
  index,
  onClick,
}: {
  citation: SummaryCitation;
  index: number;
  onClick: (c: SummaryCitation) => void;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, citation.confidence || 0)) * 100);
  return (
    <button
      type="button"
      className="chat-citation"
      title={`Open source · page ${citation.page_number}`}
      aria-label={`Open citation ${index + 1}, page ${citation.page_number}, confidence ${pct}%`}
      onClick={() => onClick(citation)}
    >
      <span className="chat-citation-head">
        <span className="chat-citation-icon" aria-hidden="true">📄</span>
        <span className="chat-citation-num">[{index + 1}]</span>
        <span className="chat-citation-page">Page {citation.page_number}</span>
        <span className="chat-citation-conf">{pct}%</span>
      </span>
      <span className="chat-citation-text">{citation.citation_text || "Cited source"}</span>
      <span className="chat-citation-bar" aria-hidden="true">
        <span className="chat-citation-bar-fill" style={{ width: `${pct}%` }} />
      </span>
    </button>
  );
}
