import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Shell } from "./layout/Shell";
import { Dashboard, CatalogPage, DetailPage } from "./features/pages";
import { pages } from "./app/catalog";
import { StatePanel } from "./components/ui";
import "./styles/tokens.css";
import { API_MODE, establishLocalSession } from "./api/client";
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1000 },
  },
});
async function start() {
  // Release is mock-only until GLM lock + same-origin authenticated BFF integration verified.
  if (API_MODE === "mock") {
    const { worker } = await import("./mocks/browser");
    await worker.start({
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
  createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<Dashboard home />} />
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
