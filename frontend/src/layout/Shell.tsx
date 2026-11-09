import { useConnection } from "../app/connection";
import { useState, useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Orbit,
  Menu,
  ShieldCheck,
  LayoutDashboard,
  ListTodo,
  Server,
  Boxes,
  Activity,
  Bot,
  Workflow,
  Network,
  Sparkles,
  FolderGit2,
  Plug,
  Cpu,
  Package,
  BookOpen,
} from "lucide-react";
const Icons = {
  Orbit,
  Menu,
  ShieldCheck,
  LayoutDashboard,
  ListTodo,
  Server,
  Boxes,
  Activity,
  Bot,
  Workflow,
  Network,
  Sparkles,
  FolderGit2,
  Plug,
  Cpu,
  Package,
  BookOpen,
};
import { useQueryClient } from "@tanstack/react-query";
import { pages } from "../app/catalog";
import { useBootstrap } from "../features/pages";
import { API_MODE } from "../api/client";
import { control, type Scenario } from "../mocks/handlers";
export function Shell() {
  const connected = useConnection();
  const [menu, setMenu] = useState(false),
    [scenario, setScenario] = useState<Scenario>("normal"),
    location = useLocation(),
    qc = useQueryClient(),
    boot = useBootstrap();
  useEffect(() => {
    setMenu(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <NavLink className="brand" to="/">
          <span className="brand-icon">M</span>
          <span>
            <strong>MagicWorkshop</strong>
            <small>PERSONAL CONTROL PLANE</small>
          </span>
        </NavLink>
        <div className="side-label">WORKSPACE / 本地工作区</div>
        <nav aria-label="主要导航">
          <NavLink to="/" end>
            <Icons.Orbit size={16} />
            架构首页 <small>V2</small>
          </NavLink>
          {pages.map(([path, label, icon], i) => {
            const Icon = Icons[icon];
            return (
              <NavLink key={path} to={`/${path}`}>
                <Icon size={16} />
                {label}
                {i > 6 && <small>{i > 11 ? "P3" : "P2"}</small>}
              </NavLink>
            );
          })}
        </nav>
        <div className="side-foot">
          <div className="version-card">
            <b>
              ◈ Spectra Motion <span>RC.1</span>
            </b>
            <p>LOCAL MOCK · 尚未部署</p>
            <div>
              <a href="/versions/v1.0/">V1.0 历史 ↗</a>
              <a href="/versions/v2.0-prism/">Prism 历史 ↗</a>
            </div>
          </div>
          <small>单用户 · 清晰边界 · 可追踪</small>
        </div>
      </aside>
      <div className="content">
        <header className="topbar">
          <div className="row">
            <button
              className="menu-button"
              aria-label="切换导航"
              aria-expanded={menu}
              onClick={() => setMenu(!menu)}
            >
              <Icons.Menu size={20} />
            </button>
            <span>
              Workspace <span className="slash">/</span>{" "}
              <strong>
                {pages.find((p) =>
                  location.pathname.startsWith(`/${p[0]}`),
                )?.[1] ?? "架构总览"}
              </strong>
            </span>
          </div>
          <div className="top-actions">
            <span className="badge mock">LOCAL MOCK</span>
            <span className="identity">
              {(boot.error ? undefined : boot.data?.identity?.display_name) ??
                "身份 UNKNOWN"}
            </span>
            <span className="avatar">M</span>
          </div>
        </header>
        <div className="connection-banner" role="status">
          <Icons.ShieldCheck size={14} />
          {!connected || scenario === "offline"
            ? "OFFLINE · 缓存只读，写操作不可用；不会提升 Mac 为写主控"
            : scenario === "stale"
              ? "STALE · 模拟观测过期，健康与新鲜度独立展示"
              : API_MODE === "mock"
                ? "纯本地演示 · 未连接生产"
                : "GLM LOOPBACK 联调 · LOCAL MOCK 数据；无生产连接"}
        </div>
        <main id="main" tabIndex={-1} className="page">
          <Outlet />
        </main>
        <footer className="footer">
          <span>MagicWorkshop / Frontend RC · MOCK ONLY</span>
          {API_MODE === "mock" && (
            <details>
              <summary>本地故障演练</summary>
              <label>
                模拟响应{" "}
                <select
                  aria-label="模拟响应"
                  value={scenario}
                  onChange={(e) => {
                    const s = e.target.value as Scenario;
                    control.scenario = s;
                    setScenario(s);
                    void qc.invalidateQueries();
                  }}
                >
                  {[
                    "normal",
                    "empty",
                    "loading",
                    "stale",
                    "offline",
                    "401",
                    "403",
                    "404",
                    "409",
                    "503",
                  ].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label>
                模拟 Worker 结果{" "}
                <select
                  aria-label="模拟 Worker 结果"
                  onChange={(e) => {
                    control.outcome = e.target.value as typeof control.outcome;
                  }}
                >
                  <option>SUCCEEDED</option>
                  <option>FAILED</option>
                  <option>NEEDS_RECONCILIATION</option>
                </select>
              </label>
            </details>
          )}
        </footer>
      </div>
    </div>
  );
}
