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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
