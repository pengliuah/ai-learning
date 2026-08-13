import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { Home } from "./pages/Home";
import { CreatePlan } from "./pages/CreatePlan";
import { PlanDetail } from "./pages/PlanDetail";
import { ModuleDetail } from "./pages/ModuleDetail";
import { Coach } from "./pages/Coach";
import { ImaSettings } from "./pages/ImaSettings";
import { RegenerateSettings } from "./pages/RegenerateSettings";
import { ModelSettings } from "./pages/ModelSettings";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Layout>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/plans/new" element={<CreatePlan />} />
              <Route path="/plans/:planId" element={<PlanDetail />} />
              <Route path="/plans/:planId/modules/:moduleId" element={<ModuleDetail />} />
              <Route path="/coach" element={<Coach />} />
              <Route path="/settings/ima" element={<ImaSettings />} />
              <Route path="/settings/regenerate" element={<RegenerateSettings />} />
              <Route path="/settings/model" element={<ModelSettings />} />
            </Routes>
          </Layout>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
