import contract from "../api/generated/contract.json" with { type: "json" };
import type { Schema } from "../api/client";
export const now = () => new Date().toISOString();
export const uuid = () => crypto.randomUUID();
export const meta = (unavailable = false): Schema<"DataSourceMeta"> => ({
  data_mode: unavailable ? "UNAVAILABLE" : "MOCK",
  freshness: "UNKNOWN",
  source_system: "synthetic-local-ledger",
  observed_at: null,
  received_at: now(),
  ttl_seconds: null,
  as_of: now(),
  reason_code: unavailable ? "NOT_AUTHORIZED" : "SYNTHETIC_ONLY",
});
export const identity: Schema<"Me"> = {
  id: "00000000-0000-4000-8000-000000000001",
  role: "local-demo",
  display_name: "本地演示用户",
  allowed_scopes: ["local:mock"],
};
export const nodes: Schema<"Node">[] = [
  ["us", "美国主控", "PRIMARY"],
  ["mac", "Mac mini", "STANDBY_GATEWAY"],
  ["ucloud", "UCloud 中继", "RELAY"],
  ["tencent", "腾讯云", "EXISTING_BUSINESS"],
].map(([id, name, role]) => ({
  id,
  name,
  role: role as Schema<"Node">["role"],
  health: "unknown",
  stale: false,
  source: "synthetic-design-catalog",
  observed_at: null,
  last_seen_at: null,
}));
export const resources: Schema<"Resource">[] = nodes.map((n) => ({
  id: `service-${n.id}`,
  display_name:
    n.id === "us"
      ? "Control Plane · 本地模拟"
      : n.id === "mac"
        ? "Mac Worker · 只读目录"
        : `${n.name} · 既有服务目录`,
  kind: "service",
  node_id: n.id,
  owner_system: "design-catalog",
  health: "unknown",
  stale: false,
  source: "synthetic-design-catalog",
  generation: 1,
  lifecycle_state: "ACTIVE",
}));
export const agents: Schema<"Agent">[] = [
  "Chief",
  "paper_",
  "复盘官",
  "Kimi",
  "dsh",
  "每日助手",
].map((display_name, i) => ({
  id: `agent-${i + 1}`,
  display_name,
  owner_system: "synthetic-catalog",
  runtime_node_id: null,
  status: "unknown",
  capabilities: i === 0 ? ["local.simulate"] : [],
}));
export const capabilities: Schema<"Capability">[] = [
  {
    name: "local.simulate",
    version: 1,
    risk: "MEDIUM",
    read_only: false,
    enabled: true,
    requires_approval: true,
    args_schema: {},
  },
  {
    name: "production.execute",
    version: 1,
    risk: "HIGH",
    read_only: false,
    enabled: false,
    requires_approval: true,
    args_schema: {},
  },
];
export const integrations: Schema<"Integration">[] = [
  "Drive",
  "Notion",
  "Colab",
].map((id) => ({
  id,
  display_name: id,
  status: "UNAVAILABLE",
  last_verified_at: null,
  scope_labels: ["未授权 · 不调用第三方 API"],
}));
const catalogs: Record<string, [string, string][]> = {
  workflows: [
    ["paper-cron", "paper_ · 旧调度目录 / Asia/Shanghai"],
    ["routine", "日常例程 · 只读 / UTC"],
  ],
  "network/links": [
    ["us-mac", "美国 → Mac · 未实测"],
    ["relay", "UCloud → 腾讯 · 设计链路"],
  ],
  models: [
    ["mac-8765", "Mac 8765 · 独立通道"],
    ["us-cliproxy", "US cliproxy · 独立通道"],
  ],
  projects: [
    ["console", "mw-console · 前端项目"],
    ["control", "mw-control-plane · GLM 负责"],
  ],
  "compute/runs": [
    ["colab", "Colab · 未授权"],
    ["checkpoint", "Checkpoint 索引 · 无真实文件"],
  ],
  knowledge: [
    ["decision", "单用户轻量主控 · 设计决策"],
    ["research", "研究索引 · Notion 未连接"],
  ],
};
export const catalog = (key: string): Schema<"DisplayRecordList"> => ({
  items: (catalogs[key] ?? []).map(([id, title]) => ({
    id,
    title,
    summary:
      key === "workflows"
        ? "只读目录；下一次执行 UNKNOWN，不触发旧任务"
        : "合成展示记录，真实来源未连接；没有运行期测量",
    source_system: "synthetic-design-catalog",
    source_meta: meta(key === "compute/runs" || key === "knowledge"),
    route_ref: null,
    enabled: false,
  })),
  next_cursor: null,
  source_meta: meta(),
});
export const bootstrap = (): Schema<"UIBootstrap"> => ({
  contract_version: contract.version,
  server_time: now(),
  app_mode: "LOCAL_MOCK",
  identity,
  features: {
    tasks: {
      status: "MOCK_ONLY",
      min_phase: "P2",
      reason: "仅修改本地模拟账本",
    },
    approvals: {
      status: "MOCK_ONLY",
      min_phase: "P2",
      reason: "不执行真实业务",
    },
    production: { status: "DISABLED", min_phase: "P3", reason: "未授权" },
  },
  source_meta: meta(),
});
