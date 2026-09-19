import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Home } from "./pages/Home";
import { CreatePlan } from "./pages/CreatePlan";
import { PlanDetail } from "./pages/PlanDetail";
import { ModuleDetail } from "./pages/ModuleDetail";
import { Coach } from "./pages/Coach";
import { ImaSettings } from "./pages/ImaSettings";
import { RegenerateSettings } from "./pages/RegenerateSettings";
import { ModelSettings } from "./pages/ModelSettings";
import { AccountSettings } from "./pages/AccountSettings";
import { SettingsIndex } from "./pages/SettingsIndex";
import { DisplaySettings } from "./pages/DisplaySettings";
import { Bookmarks } from "./pages/Bookmarks";
import { Files } from "./pages/Files";
import { Login } from "./pages/Login";
import { AdminUsers } from "./pages/AdminUsers";
import type { ReactNode } from "react";

const queryClient = new QueryClient();

/** 未登录跳登录页；记录来源路径，登录后回跳。 */
function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

/** 仅管理员可进的页面，普通用户重定向回首页。 */
function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (!user || user.role !== "admin") {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

function AppRoutes() {
  const { user } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout>
              <Home />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/plans/new"
        element={
          <RequireAuth>
            <Layout>
              <CreatePlan />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/plans/:planId"
        element={
          <RequireAuth>
            <Layout>
              <PlanDetail />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/plans/:planId/modules/:moduleId"
        element={
          <RequireAuth>
            <Layout>
              <ModuleDetail />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/coach"
        element={
          <RequireAuth>
            {/* 教练页自带滚动区: 用 wide 布局, 滚动条贴窗口边缘 */}
            <Layout wide>
              <Coach />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/settings"
        element={
          <RequireAuth>
            <Layout>
              <SettingsIndex />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/bookmarks"
        element={
          <RequireAuth>
            <Layout>
              <Bookmarks />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/files"
        element={
          <RequireAuth>
            <Layout>
              <Files />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/settings/password"
        element={
          <RequireAuth>
            <Layout>
              <AccountSettings />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/settings/display"
        element={
          <RequireAuth>
            <Layout>
              <DisplaySettings />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/settings/ima"
        element={
          <RequireAuth>
            <Layout>
              <ImaSettings />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/settings/regenerate"
        element={
          <RequireAuth>
            <Layout>
              <RegenerateSettings />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/settings/model"
        element={
          <RequireAuth>
            <Layout>
              <ModelSettings />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/admin/users"
        element={
          <RequireAuth>
            <RequireAdmin>
              <Layout>
                <AdminUsers />
              </Layout>
            </RequireAdmin>
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
