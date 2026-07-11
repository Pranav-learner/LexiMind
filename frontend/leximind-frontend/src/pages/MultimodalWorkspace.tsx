// The Multimodal AI Workspace (Phase 4, Module 5) — the unified capstone hub. Route:
//   /workspace/:workspaceId/ai
//
// Upload anything (PDF or image) and the platform automatically processes it (OCR + extraction) and
// understands it (vision) — the user never picks a pipeline. Below: workspace overview tiles, quick
// actions, a filterable asset explorer (documents, images, diagrams, tables, summaries, notes, decks,
// chats), a workspace timeline, and per-asset AI actions (summary/notes/flashcards). Everything is a
// thin surface over the orchestrator; each asset routes to its existing viewer.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as wsApi from "../api/workspace";
import { getToken } from "../api/client";
import { API_BASE } from "../api/client";
import { ApiError } from "../api/client";
import type { AssetExplorerResponse, WorkspaceAsset, WorkspaceOverview, WorkspaceTimelineEvent } from "../types";

const TYPE_META: Record<string, { icon: string; label: string; color: string }> = {
  document: { icon: "📄", label: "Documents", color: "#6366f1" },
  image: { icon: "🖼", label: "Images", color: "#f59e0b" },
  diagram: { icon: "🏗", label: "Diagrams", color: "#8b5cf6" },
  table: { icon: "▦", label: "Tables", color: "#10b981" },
  figure: { icon: "📊", label: "Figures", color: "#14b8a6" },
  summary: { icon: "📝", label: "Summaries", color: "#0ea5e9" },
  note: { icon: "🗒", label: "Notes", color: "#ec4899" },
  deck: { icon: "🎴", label: "Flashcards", color: "#f97316" },
  conversation: { icon: "💬", label: "Chats", color: "#64748b" },
};

export default function MultimodalWorkspace() {
  const { workspaceId = "" } = useParams();
  const navigate = useNavigate();
  const [overview, setOverview] = useState<WorkspaceOverview | null>(null);
  const [assets, setAssets] = useState<AssetExplorerResponse | null>(null);
  const [timeline, setTimeline] = useState<WorkspaceTimelineEvent[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const [ov, as, tl] = await Promise.all([
        wsApi.getOverview(workspaceId, controller.signal),
        wsApi.getAssets(workspaceId, filter || undefined, controller.signal),
        wsApi.getTimeline(workspaceId, controller.signal),
      ]);
      setOverview(ov); setAssets(as); setTimeline(tl.items);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof ApiError ? err.message : "Failed to load workspace.");
    }
  }, [workspaceId, filter]);

  useEffect(() => { load(); return () => abortRef.current?.abort(); }, [load]);

  async function onFiles(files: FileList | null) {
    if (!files || !files.length) return;
    setUploading(true); setError(null);
    try {
      const res = await wsApi.ingest(workspaceId, Array.from(files));
      setToast(`Uploaded ${res.uploaded} file${res.uploaded !== 1 ? "s" : ""} — processing & vision running automatically.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally { setUploading(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function runAction(a: WorkspaceAsset, action: string, focus?: string) {
    if (!a.document_id) return;
    try {
      const res = await wsApi.runAction(workspaceId, { action, document_id: a.document_id, focus });
      navigate(res.route);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    }
  }

  const filterTypes = useMemo(() => Object.keys(assets?.counts || {}), [assets]);

  return (
    <div className="ws-page mw-page">
      <header className="ws-header">
        <Link className="ws-back" to={`/workspace/${workspaceId}`}>← {overview?.name || "Workspace"}</Link>
        <div className="ws-header-right">
          <Link className="ws-btn ghost" to={`/workspace/${workspaceId}/chat`}>💬 Chat</Link>
          <Link className="ws-btn ghost" to={`/workspace/${workspaceId}/search`}>🔭 Search</Link>
          <Link className="ws-btn ghost" to={`/workspace/${workspaceId}/dashboard`}>📊 Dashboard</Link>
        </div>
      </header>

      <div className="mw-body">
        <div className="ws-page-title"><div><h1>✨ Multimodal Workspace</h1><p>Upload anything — the AI does the rest</p></div></div>

        {error && <div className="ws-error-banner">{error}</div>}
        {toast && <div className="mw-toast" onAnimationEnd={() => setToast(null)}>{toast}</div>}

        {/* overview tiles */}
        {overview && (
          <div className="mw-overview">
            <Tile icon="📄" value={overview.assets.documents} label="Documents" />
            <Tile icon="🏗" value={overview.assets.diagrams} label="Diagrams" />
            <Tile icon="▦" value={overview.assets.tables} label="Tables" />
            <Tile icon="🖼" value={overview.assets.images} label="Images" />
            <Tile icon="🔠" value={overview.modalities.ocr_pages} label="OCR pages" />
            <Tile icon="👁" value={overview.modalities.vision_assets} label="Understood" />
            <Tile icon="✅" value={`${overview.ready_documents}/${overview.assets.documents}`} label="Ready" />
          </div>
        )}

        {/* upload center */}
        <div className="mw-upload" role="button" tabIndex={0}
             onClick={() => fileRef.current?.click()}
             onKeyDown={(e) => e.key === "Enter" && fileRef.current?.click()}
             onDragOver={(e) => e.preventDefault()}
             onDrop={(e) => { e.preventDefault(); onFiles(e.dataTransfer.files); }}>
          <input ref={fileRef} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.tiff" hidden onChange={(e) => onFiles(e.target.files)} />
          <span className="mw-upload-icon">{uploading ? "⏳" : "⬆"}</span>
          <div>
            <strong>{uploading ? "Uploading & processing…" : "Upload anything"}</strong>
            <p>PDFs, scans, images, diagrams, charts, tables — dropped or clicked. Processing, OCR & vision run automatically.</p>
          </div>
        </div>

        <div className="mw-columns">
          {/* asset explorer */}
          <div className="mw-explorer">
            <div className="mw-explorer-head">
              <h2>Asset Explorer</h2>
              <div className="mw-filters">
                <button className={`search-chip${filter === "" ? " active" : ""}`} onClick={() => setFilter("")}>All</button>
                {filterTypes.map((t) => (
                  <button key={t} className={`search-chip${filter === t ? " active" : ""}`} style={{ ["--m" as string]: TYPE_META[t]?.color }} onClick={() => setFilter(t)}>
                    {TYPE_META[t]?.icon} {TYPE_META[t]?.label || t} <span className="mw-count">{assets?.counts[t]}</span>
                  </button>
                ))}
              </div>
            </div>
            {!assets || assets.items.length === 0 ? (
              <div className="ws-empty"><div className="ws-empty-mark">📦</div><h3>No assets yet</h3><p>Upload a document to populate your multimodal knowledge base.</p></div>
            ) : (
              <div className="mw-asset-grid">
                {assets.items.map((a) => <AssetCard key={`${a.asset_type}:${a.id}`} a={a} onOpen={() => a.route && navigate(a.route)} onAction={runAction} />)}
              </div>
            )}
          </div>

          {/* timeline */}
          <aside className="mw-timeline">
            <h2>Timeline</h2>
            {timeline.length === 0 ? <p className="mw-muted">No activity yet.</p> : (
              <ul>
                {timeline.map((e, i) => (
                  <li key={i} onClick={() => e.route && navigate(e.route)} role={e.route ? "button" : undefined} tabIndex={e.route ? 0 : undefined}
                      onKeyDown={(ev) => { if (ev.key === "Enter" && e.route) navigate(e.route); }}>
                    <span className="mw-tl-icon">{e.icon}</span><span className="mw-tl-title">{e.title}</span>
                  </li>
                ))}
              </ul>
            )}
          </aside>
        </div>
      </div>
    </div>
  );
}

function Tile({ icon, value, label }: { icon: string; value: number | string; label: string }) {
  return <div className="mw-tile"><span className="mw-tile-icon">{icon}</span><span className="mw-tile-value">{value}</span><span className="mw-tile-label">{label}</span></div>;
}

function AssetCard({ a, onOpen, onAction }: { a: WorkspaceAsset; onOpen: () => void; onAction: (a: WorkspaceAsset, action: string, focus?: string) => void }) {
  const [menu, setMenu] = useState(false);
  const meta = TYPE_META[a.asset_type] || { icon: "•", label: a.asset_type, color: "#888" };
  const canAct = !!a.document_id && ["document", "diagram", "table", "image", "figure"].includes(a.asset_type);
  return (
    <div className="mw-asset" style={{ ["--m" as string]: meta.color }}>
      <div className="mw-asset-main" onClick={onOpen} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
        {a.thumbnail_url ? <Thumb url={a.thumbnail_url} icon={meta.icon} /> : <span className="mw-asset-icon">{meta.icon}</span>}
        <div className="mw-asset-body">
          <div className="mw-asset-title">{a.title}</div>
          <div className="mw-asset-sub">{a.subtitle}</div>
        </div>
      </div>
      {canAct && (
        <div className="mw-asset-actions">
          <button className="ws-icon-btn" aria-label="AI actions" onClick={() => setMenu((o) => !o)}>⚡</button>
          {menu && (
            <div className="note-menu-pop" onMouseLeave={() => setMenu(false)}>
              <button onClick={() => { onAction(a, "summary"); setMenu(false); }}>📝 Summarize</button>
              <button onClick={() => { onAction(a, "notes", a.asset_type === "document" ? undefined : `${a.asset_type}s`); setMenu(false); }}>🗒 Notes</button>
              <button onClick={() => { onAction(a, "flashcards", a.asset_type === "document" ? undefined : `${a.asset_type}s`); setMenu(false); }}>🎴 Flashcards</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Thumb({ url, icon }: { url: string; icon: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let obj: string | null = null;
    const token = getToken();
    fetch(`${API_BASE}${url}`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined })
      .then((r) => (r.ok ? r.blob() : null)).then((b) => { if (b) { obj = URL.createObjectURL(b); setSrc(obj); } }).catch(() => {});
    return () => { if (obj) URL.revokeObjectURL(obj); };
  }, [url]);
  return <span className="mw-asset-thumb">{src ? <img src={src} alt="" onError={(e) => (e.currentTarget.style.display = "none")} /> : <span className="mw-asset-icon">{icon}</span>}</span>;
}
