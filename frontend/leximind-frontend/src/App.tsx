// Routing + auth gating.
//
// Pages are lazy-loaded (React.lazy) so the login screen ships without the dashboard bundle
// and vice-versa. `RequireAuth` gates the app: unauthenticated users are redirected to
// /login; the workspace context (/workspace/:workspaceId) is nested so future modules can
// hang off it without touching the router shell.

import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./context/AuthContext";

const Login = lazy(() => import("./pages/Login"));
const WorkspacesDashboard = lazy(() => import("./pages/WorkspacesDashboard"));
const WorkspaceDetail = lazy(() => import("./pages/WorkspaceDetail"));
const DocumentsLibrary = lazy(() => import("./pages/DocumentsLibrary"));
const PdfViewer = lazy(() => import("./pages/PdfViewer"));
const ChatWorkspace = lazy(() => import("./pages/ChatWorkspace"));
const SummariesDashboard = lazy(() => import("./pages/SummariesDashboard"));
const NotesDashboard = lazy(() => import("./pages/NotesDashboard"));
const NoteEditorPage = lazy(() => import("./pages/NoteEditorPage"));
const FlashcardsDashboard = lazy(() => import("./pages/FlashcardsDashboard"));
const DeckView = lazy(() => import("./pages/DeckView"));
const ReviewSession = lazy(() => import("./pages/ReviewSession"));
const KnowledgeExplorer = lazy(() => import("./pages/KnowledgeExplorer"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const MultimodalSearch = lazy(() => import("./pages/MultimodalSearch"));
const ContextInspector = lazy(() => import("./pages/ContextInspector"));
const MultimodalWorkspace = lazy(() => import("./pages/MultimodalWorkspace"));
const MediaWorkspace = lazy(() => import("./pages/MediaWorkspace"));
const TemporalSearch = lazy(() => import("./pages/TemporalSearch"));
const MediaAIWorkspace = lazy(() => import("./pages/MediaAIWorkspace"));
const AgentDebugPanel = lazy(() => import("./pages/AgentDebugPanel"));
const AgentWorkspace = lazy(() => import("./pages/AgentWorkspace"));
const VerificationInspector = lazy(() => import("./pages/VerificationInspector"));
const OrchestrationDashboard = lazy(() => import("./pages/OrchestrationDashboard"));
const KnowledgeGraphInspector = lazy(() => import("./pages/KnowledgeGraphInspector"));
const SemanticMemoryExplorer = lazy(() => import("./pages/SemanticMemoryExplorer"));
const GraphReasoningInspector = lazy(() => import("./pages/GraphReasoningInspector"));
const KnowledgeWorkspace = lazy(() => import("./pages/KnowledgeWorkspace"));
const EvaluationWorkspace = lazy(() => import("./pages/EvaluationWorkspace"));

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Splash />;
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />;
  return <>{children}</>;
}

function Splash() {
  return (
    <div className="ws-splash">
      <span className="ws-brand-mark spin">🧠</span>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();

  return (
    <Suspense fallback={<Splash />}>
      <Routes>
        <Route
          path="/login"
          element={loading ? <Splash /> : user ? <Navigate to="/" replace /> : <Login />}
        />
        <Route
          path="/"
          element={
            <RequireAuth>
              <WorkspacesDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId"
          element={
            <RequireAuth>
              <WorkspaceDetail />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/library"
          element={
            <RequireAuth>
              <DocumentsLibrary />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/document/:documentId"
          element={
            <RequireAuth>
              <PdfViewer />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/chat"
          element={
            <RequireAuth>
              <ChatWorkspace />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/chat/:conversationId"
          element={
            <RequireAuth>
              <ChatWorkspace />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/summaries"
          element={
            <RequireAuth>
              <SummariesDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/summaries/:summaryId"
          element={
            <RequireAuth>
              <SummariesDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/notes"
          element={
            <RequireAuth>
              <NotesDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/notes/:noteId"
          element={
            <RequireAuth>
              <NoteEditorPage />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/flashcards"
          element={
            <RequireAuth>
              <FlashcardsDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/flashcards/deck/:deckId"
          element={
            <RequireAuth>
              <DeckView />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/flashcards/review"
          element={
            <RequireAuth>
              <ReviewSession />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/knowledge"
          element={
            <RequireAuth>
              <KnowledgeExplorer />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/dashboard"
          element={
            <RequireAuth>
              <Dashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/search"
          element={
            <RequireAuth>
              <MultimodalSearch />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/context"
          element={
            <RequireAuth>
              <ContextInspector />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/ai"
          element={
            <RequireAuth>
              <MultimodalWorkspace />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/media"
          element={
            <RequireAuth>
              <MediaWorkspace />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/temporal"
          element={
            <RequireAuth>
              <TemporalSearch />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/media-ai"
          element={
            <RequireAuth>
              <MediaAIWorkspace />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/agent"
          element={
            <RequireAuth>
              <AgentDebugPanel />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/agents"
          element={
            <RequireAuth>
              <AgentWorkspace />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/verification"
          element={
            <RequireAuth>
              <VerificationInspector />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/orchestration"
          element={
            <RequireAuth>
              <OrchestrationDashboard />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/graph"
          element={
            <RequireAuth>
              <KnowledgeGraphInspector />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/memory"
          element={
            <RequireAuth>
              <SemanticMemoryExplorer />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/reasoning"
          element={
            <RequireAuth>
              <GraphReasoningInspector />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/knowledge"
          element={
            <RequireAuth>
              <KnowledgeWorkspace />
            </RequireAuth>
          }
        />
        <Route
          path="/workspace/:workspaceId/evaluation"
          element={
            <RequireAuth>
              <EvaluationWorkspace />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
