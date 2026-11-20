import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { api } from "./lib/api";
import { AuthProvider, useAuth } from "./lib/auth";
import type { Role } from "./lib/types";
import AuditPage from "./pages/Audit";
import DashboardPage from "./pages/Dashboard";
import { NextReviewRedirect } from "./components/v2/viewer/PipelineTab";
import DocumentsPage from "./pages/Documents";
import LoginPage from "./pages/Login";
import SetupPage from "./pages/Setup";
import UsersPage from "./pages/Users";

const SettingsPage = lazy(() => import("./pages/Settings"));
const ChatTestPage = lazy(() => import("./pages/ChatTest"));
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

/** Link cũ /documents/:docId/view?… → /documents/:docId?… */
function ViewRedirect() {
  const { docId = "" } = useParams();
  const { search } = useLocation();
  return <Navigate to={`/documents/${docId}${search}`} replace />;
}

/** Màn review cũ đã bỏ: /documents/:docId/pages/:page → tab 検査, /documents/:docId/chunks → tab チャンク. */
function LegacyRedirect({ tab }: { tab: "inspect" | "chunks" }) {
  const { docId = "", page } = useParams();
  return <Navigate to={`/documents/${docId}?tab=${tab}${page ? `&page=${page}` : ""}`} replace />;
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
        <Route index element={<Navigate to="/documents" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="documents/:docId" element={<DocumentViewerPage />} />
        <Route path="documents/:docId/review" element={<NextReviewRedirect />} />
        <Route path="documents/:docId/view" element={<ViewRedirect />} />
        <Route path="documents/:docId/pages/:page" element={<LegacyRedirect tab="inspect" />} />
        <Route path="documents/:docId/chunks" element={<LegacyRedirect tab="chunks" />} />
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
