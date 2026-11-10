import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Shell } from "./layout/Shell";
import { Dashboard, CatalogPage, DetailPage } from "./features/pages";
import { pages } from "./app/catalog";
import { StatePanel } from "./components/ui";
import "./styles/tokens.css";
import {
  API_MODE,
  ApiError,
  establishLocalSession,
  establishWebSession,
} from "./api/client";
import {
  WorkspaceLayout,
  WorkspaceHome,
  WorkspaceHistory,
  WorkspaceResults,
  WorkspaceAssistants,
  WorkspaceTask,
} from "./workspace/Workspace";
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1000 },
  },
});
async function start() {
  // Session deployments use the existing authenticated server and never mint a local actor.
  if (API_MODE === "mock") {
    const { worker } = await import("./mocks/browser");
    await worker.start({
      serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
      onUnhandledRequest(request, print) {
        if (new URL(request.url).pathname.startsWith("/api/")) print.error();
      },
    });
  }
  if (API_MODE === "loopback") {
    try {
      await establishLocalSession();
    } catch {
      createRoot(document.getElementById("root")!).render(
        <StatePanel kind="OFFLINE" retry={() => location.reload()}>
          LOCAL INTEGRATION · 本地会话未建立，请检查新 BFF 后刷新。
        </StatePanel>,
      );
      return;
    }
  }
  if (API_MODE === "session") {
    try {
      await establishWebSession();
    } catch (error) {
      createRoot(document.getElementById("root")!).render(
        <StatePanel
          kind={error instanceof ApiError ? String(error.status) : "OFFLINE"}
          retry={() => location.reload()}
        >
          未能验证当前登录会话，工作台没有加载。
          <a className="button" href="/">
            返回登录
          </a>
        </StatePanel>,
      );
      return;
    }
  }
  createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter
        basename={import.meta.env.BASE_URL.replace(/\/$/, "") || "/"}
      >
        <Routes>
          <Route element={<WorkspaceLayout />}>
            <Route index element={<WorkspaceHome />} />
            <Route path="workbench" element={<WorkspaceHome />} />
            <Route path="workbench/history" element={<WorkspaceHistory />} />
            <Route path="workbench/results" element={<WorkspaceResults />} />
            <Route
              path="workbench/assistants"
              element={<WorkspaceAssistants />}
            />
            <Route path="workbench/tasks/:id" element={<WorkspaceTask />} />
          </Route>
          <Route element={<Shell />}>
            <Route path="architecture" element={<Dashboard home />} />
            {pages.map(([k]) => (
              <Route
                key={k}
                path={k}
                element={
                  k === "dashboard" ? (
                    <Dashboard />
                  ) : (
                    <CatalogPage key={k} pageKey={k} />
                  )
                }
              />
            ))}
            {(["tasks", "nodes", "services", "agents"] as const).map((k) => (
              <Route
                key={k}
                path={`${k}/:id`}
                element={<DetailPage kind={k} />}
              />
            ))}
            <Route
              path="*"
              element={<StatePanel kind="404">没有这个页面。</StatePanel>}
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>,
  );
}
void start();
