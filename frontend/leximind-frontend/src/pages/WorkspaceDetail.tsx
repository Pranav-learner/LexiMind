// A single workspace's home. Route: /workspace/:workspaceId.
//
// This is the context boundary every FUTURE Phase-3 module inherits: documents, chats,
// notes, and flashcards will render here, all implicitly scoped to `workspaceId`. Today it
// hosts the (workspace-scoped) PDF upload and Q&A carried over from the MVP.

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import * as api from "../api/workspaces";
import { ApiError } from "../api/client";
import UploadPdf from "../components/UploadPdf";
import AskQuestion from "../components/AskQuestion";
import type { Workspace } from "../types";

// Collaboration Components & Context
import { CollaborationProvider } from "../context/CollaborationContext";
import OrganizationSwitcher from "../components/collaboration/OrganizationSwitcher";
import WorkspaceShareModal from "../components/collaboration/WorkspaceShareModal";
import CommentPanel from "../components/collaboration/CommentPanel";
import ActivityTimeline from "../components/collaboration/ActivityTimeline";
import PresenceIndicator from "../components/collaboration/PresenceIndicator";

export default function WorkspaceDetail() {
  const { workspaceId = "" } = useParams();
  const [ws, setWs] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setWs(await api.getWorkspace(workspaceId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load workspace.");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <div className="ws-page"><div className="ws-page-body">Loading…</div></div>;
  if (error || !ws)
    return (
      <div className="ws-page">
        <div className="ws-page-body">
          <div className="ws-error-banner">{error || "Workspace not found."}</div>
          <Link className="ws-link" to="/">← Back to workspaces</Link>
        </div>
      </div>
    );

  return (
    <CollaborationProvider workspaceId={ws.id}>
      <WorkspaceDetailInner ws={ws} onReload={load} />
    </CollaborationProvider>
  );
}

interface InnerProps {
  ws: Workspace;
  onReload: () => Promise<void>;
}

function WorkspaceDetailInner({ ws, onReload }: InnerProps) {
  const [showShareModal, setShowShareModal] = useState(false);

  return (
    <div className="ws-page">
      <header className="ws-header" style={{ ["--ws-accent" as string]: ws.color }}>
        <div className="ws-header-left-col">
          <Link className="ws-back" to="/">← Workspaces</Link>
          <div className="ws-detail-title">
            <span className="ws-card-icon" style={{ background: ws.color }}>{ws.icon}</span>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <h1>{ws.name}</h1>
                <button className="ws-btn primary small" onClick={() => setShowShareModal(true)}>
                  🤝 Share
                </button>
              </div>
              {ws.description && <p>{ws.description}</p>}
            </div>
          </div>
        </div>

        <div className="ws-header-right-col" style={{ display: "flex", gap: 15, alignItems: "center" }}>
          <OrganizationSwitcher />
        </div>
      </header>

      {/* Grid Layout: Main Workspace + Collaboration sidebar */}
      <div className="ws-page-body collab-grid-layout" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 24, padding: "20px" }}>
        
        {/* Left Column: Traditional Workspace Content */}
        <div className="ws-main-col" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div className="ws-detail-stats">
            <Stat label="Documents" value={ws.document_count} />
            <Stat label="Chats" value={ws.chat_count} />
            <Stat label="Notes" value={ws.note_count} />
            <Stat label="Flashcards" value={ws.flashcard_count} />
            <Stat label="Summaries" value={ws.summary_count} />
          </div>

          <div className="ws-page-title">
            <div style={{ display: "flex", gap: 10 }}>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/ai`}>
                ✨ AI Workspace
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/dashboard`}>
                📊 Dashboard
              </Link>
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/chat`}>
                💬 Open Chat
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/summaries`}>
                📄 Summaries
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/notes`}>
                📝 Notes
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/flashcards`}>
                🎴 Flashcards
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/knowledge`}>
                🔎 Knowledge
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/search`}>
                🔭 Search
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/context`}>
                🧠 Context
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/media-ai`}>
                🎧 Media AI Workspace
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/knowledge`}>
                🌐 Knowledge Workspace
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/evaluation`}>
                📊 Evaluation
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/operations`}>
                🛰️ AI Operations
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/optimization`}>
                ⚙️ AI Optimization
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/learning`}>
                🔁 Continuous Learning
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/security`}>
                🛡️ Security &amp; Governance
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/integrations`}>
                🔌 Integrations &amp; Automation
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/graph`}>
                🕸️ Knowledge Graph
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/memory`}>
                🧠 Semantic Memory
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/reasoning`}>
                🧩 Graph Reasoning
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/orchestration`}>
                🕹️ Agent Orchestration
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/agents`}>
                🧑‍🔬 Agent Workspace
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/verification`}>
                🛡️ Verification Inspector
              </Link>
              <Link className="ws-btn primary ws-dashboard-cta" to={`/workspace/${ws.id}/agent`}>
                🤖 Agent Runtime
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/media`}>
                🎬 Audio &amp; Video
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/temporal`}>
                ⏱ Temporal Search
              </Link>
              <Link className="ws-btn primary" to={`/workspace/${ws.id}/library`}>
                📚 Open Document Library
              </Link>
            </div>
          </div>

          <section className="ws-panel">
            <UploadPdf workspaceId={ws.id} onUploaded={onReload} />
          </section>
          <section className="ws-panel">
            <AskQuestion workspaceId={ws.id} />
          </section>
        </div>

        {/* Right Column: Collaboration, Presence, Comments, Feed */}
        <div className="ws-collab-col" style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <PresenceIndicator />
          <CommentPanel targetType="workspace" targetId={ws.id} />
          <ActivityTimeline />
        </div>
      </div>

      {showShareModal && (
        <WorkspaceShareModal
          workspaceId={ws.id}
          workspaceName={ws.name}
          onClose={() => setShowShareModal(false)}
          onOwnershipTransferred={onReload}
        />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="ws-stat big">
      <span className="ws-stat-value">{value}</span>
      <span className="ws-stat-label">{label}</span>
    </div>
  );
}
