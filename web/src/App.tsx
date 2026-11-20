import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { api } from "./lib/api";
import { AuthProvider, useAuth } from "./lib/auth";
import type { Role } from "./lib/types";
import AuditPage from "./pages/Audit";
import DashboardPage from "./pages/Dashboard";
import DocumentDetailPage, { NextReviewRedirect } from "./pages/DocumentDetail";
import DocumentsPage from "./pages/Documents";
import JobsPage from "./pages/Jobs";
import LoginPage from "./pages/Login";
import SearchPage from "./pages/SearchTest";
import SetupPage from "./pages/Setup";
import UsersPage from "./pages/Users";

const PageReviewPage = lazy(() => import("./pages/PageReview"));
const ChunkReviewPage = lazy(() => import("./pages/ChunkReview"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const ChatTestPage = lazy(() => import("./pages/ChatTest"));
const LibraryPage = lazy(() => import("./pages/v2/Library"));
const NotebookPage = lazy(() => import("./pages/v2/Notebook"));
const DocumentViewerPage = lazy(() => import("./pages/v2/DocumentViewer"));

function Splash() {
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      <Loader2 className="size-6 animate-spin" />
    </div>
  );
}

function Guard({ children, role = "viewer" }: { children: React.ReactNode; role?: Role }) {
  const { user, loading, can } = useAuth();
  const loc = useLocation();
  if (loading) return <Splash />;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (!can(role)) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function Routed() {
  const setup = useQuery({
    queryKey: ["setup-status"],
    queryFn: () => api.get<{ needs_setup: boolean }>("/setup/status"),
    staleTime: Infinity,
  });
  const loc = useLocation();
  if (setup.isLoading) return <Splash />;
  if (setup.data?.needs_setup && loc.pathname !== "/setup") return <Navigate to="/setup" replace />;
  return (
    <Suspense fallback={<Splash />}>
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <Guard>
            <AppShell />
          </Guard>
        }
      >
        <Route index element={<Navigate to="/library" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="notebooks/:nbId" element={<NotebookPage />} />
        <Route path="notebooks/:nbId/sources/:docId" element={<DocumentViewerPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="documents/:docId" element={<DocumentDetailPage />} />
        <Route path="documents/:docId/review" element={<NextReviewRedirect />} />
        <Route path="documents/:docId/pages/:page" element={<PageReviewPage />} />
        <Route path="documents/:docId/chunks" element={<ChunkReviewPage />} />
        <Route path="jobs" element={<JobsPage />} />
        <Route path="search" element={<Navigate to="/test/search" replace />} />
        <Route
          path="test/search"
          element={
            <Guard role="reviewer">
              <SearchPage />
            </Guard>
          }
        />
        <Route
          path="test/chat"
          element={
            <Guard role="reviewer">
              <ChatTestPage />
            </Guard>
          }
        />
        <Route
          path="settings"
          element={
            <Guard role="admin">
              <SettingsPage />
            </Guard>
          }
        />
        <Route
          path="users"
          element={
            <Guard role="admin">
              <UsersPage />
            </Guard>
          }
        />
        <Route
          path="audit"
          element={
            <Guard role="admin">
              <AuditPage />
            </Guard>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routed />
    </AuthProvider>
  );
}
