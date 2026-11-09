import { api, required } from "../api/client";
export const pages = [
  [
    "dashboard",
    "总控制台",
    "LayoutDashboard",
    "Overview",
    "四节点概况、任务与近期事件",
  ],
  [
    "tasks",
    "任务工作台",
    "ListTodo",
    "Operations",
    "从意图到结果，每一步都有记录",
  ],
  [
    "approvals",
    "权限与审批",
    "ShieldCheck",
    "Operations",
    "先确认风险，再推进本地模拟",
  ],
  [
    "nodes",
    "四节点管理",
    "Server",
    "Infrastructure",
    "唯一写主控与只读备用，职责清晰",
  ],
  [
    "services",
    "服务目录",
    "Boxes",
    "Infrastructure",
    "按归属和节点查看，只读展示",
  ],
  [
    "observability",
    "观测与事件",
    "Activity",
    "Operations",
    "健康观测与操作事件分别追踪",
  ],
  [
    "agents",
    "Agent 中心",
    "Bot",
    "Intelligence",
    "Identity · Capability · Worker",
  ],
  [
    "workflows",
    "调度工作流",
    "Workflow",
    "Intelligence",
    "旧 cron 与 routine 的只读目录",
  ],
  [
    "network",
    "入口与网络",
    "Network",
    "Infrastructure",
    "设计链路不代表实际可达",
  ],
  [
    "models",
    "模型路由",
    "Sparkles",
    "Intelligence",
    "Mac 8765 与 US cliproxy 独立展示",
  ],
  [
    "projects",
    "代码项目",
    "FolderGit2",
    "Workspace",
    "项目、测试摘要与工作项索引",
  ],
  ["integrations", "连接器与设置", "Plug", "Workspace", "授权范围决定可用能力"],
  ["compute", "计算中心", "Cpu", "Workspace", "实验、计算与 checkpoint 索引"],
  ["artifacts", "文件产物", "Package", "Workspace", "URI、校验和与来源任务"],
  [
    "knowledge",
    "知识与决策",
    "BookOpen",
    "Workspace",
    "只读研究索引与决策记录",
  ],
] as const;
export type PageKey = (typeof pages)[number][0];
export const readCatalog = {
  tasks: async (cursor?: string) =>
    required(await api.GET("/api/v1/tasks", { params: { query: { cursor } } })),
  approvals: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/approvals", { params: { query: { cursor } } }),
    ),
  nodes: async (cursor?: string) =>
    required(await api.GET("/api/v1/nodes", { params: { query: { cursor } } })),
  services: async (cursor?: string) => {
    const result = required(
      await api.GET("/api/v1/resources", { params: { query: { cursor } } }),
    );
    return {
      ...result,
      items: result.items.filter((r) => r.kind === "service"),
    };
  },
  observability: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/events/history", {
        params: { query: { cursor } },
      }),
    ),
  agents: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/agents", { params: { query: { cursor } } }),
    ),
  workflows: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/workflows", { params: { query: { cursor } } }),
    ),
  network: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/network/links", { params: { query: { cursor } } }),
    ),
  models: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/models", { params: { query: { cursor } } }),
    ),
  projects: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/projects", { params: { query: { cursor } } }),
    ),
  integrations: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/integrations", { params: { query: { cursor } } }),
    ),
  compute: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/compute/runs", { params: { query: { cursor } } }),
    ),
  artifacts: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/artifacts", { params: { query: { cursor } } }),
    ),
  knowledge: async (cursor?: string) =>
    required(
      await api.GET("/api/v1/knowledge", { params: { query: { cursor } } }),
    ),
};
