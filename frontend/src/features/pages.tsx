import { control } from "../mocks/handlers";
import { useConnection } from "../app/connection";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { ArrowUpRight, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import {
  api,
  required,
  subscribeEvents,
  ApiError,
  API_MODE,
  type Schema,
} from "../api/client";
import { pages, readCatalog, type PageKey } from "../app/catalog";
import {
  ConfirmationDialog,
  CursorPagination,
  EntityDetailTabs,
  FeatureGate,
  FilterToolbar,
  HealthBadge,
  KeyValues,
  ProvenanceTooltip,
  QueryState,
  RiskApprovalPanel,
  StatePanel,
  TaskTimeline,
} from "../components/ui";
import { GraphCanvas } from "./GraphCanvas";
export function useBootstrap() {
  return useQuery({
    queryKey: ["bootstrap"],
    queryFn: async () => required(await api.GET("/api/v1/ui/bootstrap")),
    staleTime: 30000,
  });
}
function denied(error: Error | null) {
  return error instanceof ApiError && [401, 403, 404].includes(error.status);
}
export function useEvents() {
  const qc = useQueryClient(),
    [connection, setConnection] = useState("CONNECTING");
  useEffect(() => {
    let stop: undefined | (() => void);
    const connect = () => {
      stop?.();
      if (!document.hidden)
        stop = subscribeEvents(
          () => {
            setConnection("MOCK STREAM");
            void qc.invalidateQueries({
              queryKey: ["catalog", "observability"],
            });
          },
          () => setConnection("LIVE PAUSED · 轮询 15s / 自动重连"),
        );
    };
    connect();
    document.addEventListener("visibilitychange", connect);
    return () => {
      stop?.();
      document.removeEventListener("visibilitychange", connect);
    };
  }, [qc]);
  return connection;
}
export function PageHeader({
  kicker,
  title,
  description,
  children,
}: {
  kicker: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <div className="overline">{kicker} / MAGICWORKSHOP</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="header-actions">{children}</div>
    </header>
  );
}
export function Dashboard({ home = false }: { home?: boolean }) {
  const q = useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => required(await api.GET("/api/v1/dashboard/summary")),
  });
  return (
    <>
      <PageHeader
        kicker={home ? "SPECTRA MOTION / V2.0" : "OVERVIEW"}
        title={home ? "让每一份算力，各就其位。" : "总控制台"}
        description={
          home
            ? "统一入口，清晰边界。把节点、Agent 与任务连接成可追踪的工作流。"
            : "所有状态带有来源。未知不等于健康，缓存不等于在线。"
        }
      >
        <Link className="button primary" to="/">
          进入用户工作坊 <ArrowUpRight size={15} />
        </Link>
      </PageHeader>
      <div className="meta-strip">
        <span>◉ LOCAL MOCK · 无生产连接</span>
        <span>单用户 / 1 个计划写主控</span>
        <span>本地集成 RC · 无生产连接</span>
      </div>
      <QueryState
        error={q.error}
        loading={q.isPending}
        retry={() => void q.refetch()}
      />
      {q.data && !denied(q.error) && (
        <>
          {(q.data.task_counts.needs_reconciliation ?? 0) > 0 && (
            <div className="notice" role="alert">
              有本地任务待对账；自动重排已暂停。
              <Link to="/tasks">查看任务 ↗</Link>
            </div>
          )}
          <div className="stats-grid">
            {[
              [
                "节点目录",
                String(q.data.nodes.items.length),
                "设计目录，不代表在线",
              ],
              [
                "活跃模拟任务",
                String(q.data.task_counts.active ?? "—"),
                "仅新平台本地账本",
              ],
              [
                "待审请求",
                String(q.data.approval_counts.pending ?? "—"),
                "MEDIUM · 本地模拟",
              ],
              [
                "外部任务统计",
                String(q.data.task_counts.external ?? "—"),
                "暂无可靠统计",
              ],
            ].map(([label, v, caption], i) => (
              <div className={`stat-tile tile-${i}`} key={label}>
                <small>{label}</small>
                <b>{v}</b>
                <p>{caption}</p>
                <span className="stat-icon">{["◈", "⌘", "◇", "↗"][i]}</span>
              </div>
            ))}
          </div>
          {home ? (
            <div className="home-workspace">
              <GraphCanvas />
              <aside className="panel architecture-notes">
                <div className="overline">CONTROL PLANE</div>
                <h2>
                  单一主控，
                  <br />
                  多端协同。
                </h2>
                <p>
                  美国主控是唯一计划写入口。Mac 保持只读备用与本地 Worker 角色。
                </p>
                <div className="separator" />
                <h3>数据可信边界</h3>
                <p>展示的是合成目录。没有真实探针、模型调用或旧系统行为。</p>
                <HealthBadge value="UNKNOWN" />
                <ProvenanceTooltip meta={q.data.source_meta} />
                <Link to="/network">查看网络目录 ↗</Link>
              </aside>
            </div>
          ) : (
            <div className="node-grid">
              {q.data.nodes.items.map((n) => (
                <Link
                  className={`panel node-card node-${n.role.toLowerCase()}`}
                  to={`/nodes/${n.id}`}
                  key={n.id}
                >
                  <small>{n.role}</small>
                  <h2>{n.name}</h2>
                  <HealthBadge value={n.health} />
                  <HealthBadge value={n.stale ? "STALE" : "UNKNOWN"} />
                  <p>{n.source}</p>
                  <p>最近见到：{n.last_seen_at ?? "—"}</p>
                </Link>
              ))}
            </div>
          )}
          <div className="two-col">
            <section className="panel">
              <div className="section-head">
                <h2>近期事件</h2>
                <Link to="/observability">全部事件 ↗</Link>
              </div>
              {q.data.recent_events.length ? (
                q.data.recent_events.map((e) => (
                  <div className="event-row" key={e.id}>
                    <HealthBadge value={e.action} />
                    <time>{new Date(e.created_at).toLocaleTimeString()}</time>
                  </div>
                ))
              ) : (
                <p className="muted">
                  暂无事件。创建一条本地模拟任务，开始追踪。
                </p>
              )}
            </section>
            <section className="panel">
              <div className="section-head">
                <h2>能力入口</h2>
                <small>READ ONLY / MOCK</small>
              </div>
              <div className="quick-grid">
                {[
                  ["agents", "Agent 中心"],
                  ["models", "模型通道"],
                  ["compute", "计算中心"],
                  ["knowledge", "知识决策"],
                ].map(([path, label]) => (
                  <Link key={path} to={`/${path}`}>
                    {label}
                    <ArrowUpRight size={14} />
                  </Link>
                ))}
              </div>
            </section>
          </div>
          <ProvenanceTooltip meta={q.data.source_meta} />
        </>
      )}
    </>
  );
}

type Row = {
  id: string;
  title: string;
  status: string;
  owner: string;
  detail?: string;
  data: object;
};
function toRows(key: Exclude<PageKey, "dashboard">, items: object[]): Row[] {
  return items.map((obj, i) => {
    const d = obj as Record<string, unknown>;
    const id = String(d.id ?? d.resource_id ?? i);
    return {
      id,
      title: String(
        d.title ??
          d.name ??
          d.display_name ??
          d.action ??
          d.uri ??
          d.capability ??
          id,
      ),
      status: String(
        d.state ??
          d.health ??
          d.status ??
          (d.source_meta as Schema<"DataSourceMeta"> | undefined)?.data_mode ??
          "UNKNOWN",
      ),
      owner: String(
        d.owner_system ??
          d.source_system ??
          d.source ??
          d.role ??
          d.storage_system ??
          "LOCAL MOCK",
      ),
      detail: ["nodes", "services", "agents", "tasks"].includes(key)
        ? `/${key}/${id}`
        : undefined,
      data: obj,
    };
  });
}
export function CatalogPage({
  pageKey,
}: {
  pageKey: Exclude<PageKey, "dashboard">;
}) {
  const connected = useConnection();
  const cfg = pages.find((p) => p[0] === pageKey)!;
  const [search, setSearch] = useState(""),
    [status, setStatus] = useState(""),
    [sort, setSort] = useState(false),
    [page, setPage] = useState(0),
    [selected, setSelected] = useState<Row | null>(null),
    [create, setCreate] = useState(false),
    [decision, setDecision] = useState<{
      approval: Schema<"Approval">;
      reject: boolean;
    } | null>(null),
    [notice, setNotice] = useState(""),
    [timeRange, setTimeRange] = useState("all"),
    [cursor, setCursor] = useState<string | undefined>();
  const query = useQuery({
    queryKey: ["catalog", pageKey, cursor],
    queryFn: async () => readCatalog[pageKey](cursor),
    refetchInterval: pageKey === "observability" ? 15000 : false,
    refetchIntervalInBackground: false,
  });
  const boot = useBootstrap(),
    qc = useQueryClient();
  const connection = useEvents();
  const taskQuery = useQuery({
    queryKey: ["catalog", "tasks"],
    queryFn: () => readCatalog.tasks(),
    enabled: pageKey === "approvals",
  });
  const approvalMutation = useMutation({
    mutationFn: async () => {
      if (!decision) throw Error("无审批");
      const path = decision.reject
        ? "/api/v1/approvals/{id}/reject"
        : "/api/v1/approvals/{id}/approve";
      return required(
        await api.POST(path, {
          params: { path: { id: decision.approval.id } },
        }),
      );
    },
    onSuccess: () => {
      setDecision(null);
      setNotice("LOCAL MOCK 审批已提交");
      void qc.invalidateQueries();
    },
    onError: (e) => setNotice(e.message),
  });
  const rows = toRows(
    pageKey,
    denied(query.error) ? [] : (query.data?.items ?? []),
  );
  const filtered = rows
    .filter(
      (r) =>
        (!status || r.status === status) &&
        `${r.title} ${r.status} ${r.owner} ${JSON.stringify(r.data)}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    )
    .filter((r) => {
      if (pageKey !== "observability" || timeRange === "all") return true;
      const created = (r.data as Schema<"AuditEvent">).created_at;
      return Date.parse(created) > Date.now() - Number(timeRange) * 3600000;
    })
    .sort((a, b) => (sort ? -1 : 1) * a.title.localeCompare(b.title));
  const resetSearch = (s: string) => {
    setSearch(s);
    setPage(0);
  };
  return (
    <>
      <PageHeader kicker={cfg[3]} title={cfg[1]} description={cfg[4]}>
        <button onClick={() => void query.refetch()}>
          <RefreshCw size={14} /> 刷新
        </button>
        {pageKey === "tasks" && (
          <FeatureGate
            allowed={
              connected &&
              !boot.error &&
              boot.data?.app_mode === "LOCAL_MOCK" &&
              boot.data.features.tasks?.status === "MOCK_ONLY"
            }
            reason={connected ? "仅 LOCAL_MOCK 可创建" : "OFFLINE · 缓存只读"}
          >
            <button className="primary" onClick={() => setCreate(true)}>
              <Plus size={15} /> 新建模拟任务
            </button>
          </FeatureGate>
        )}
      </PageHeader>
      <div className="meta-strip">
        <span>LOCAL MOCK · 合成目录</span>
        <span>
          {pageKey === "observability"
            ? connection
            : "READ ONLY / LOCAL LEDGER"}
        </span>
        <span>生产执行锁定</span>
      </div>
      {["compute", "knowledge", "integrations"].includes(pageKey) && (
        <div className="notice">
          <ShieldCheck size={18} /> 真实来源 UNAVAILABLE ·
          尚未授权，当前仅展示本地目录，不调用第三方。
        </div>
      )}
      {pageKey === "network" && <GraphCanvas />}
      <section className="panel list-panel">
        <FilterToolbar
          search={search}
          setSearch={resetSearch}
          status={status}
          setStatus={(s) => {
            setStatus(s);
            setPage(0);
          }}
          options={[...new Set(rows.map((r) => r.status))]}
          sort={sort}
          setSort={setSort}
        />
        {pageKey === "observability" && (
          <label className="time-filter">
            时间范围{" "}
            <select
              aria-label="时间范围"
              value={timeRange}
              onChange={(e) => {
                setTimeRange(e.target.value);
                setPage(0);
              }}
            >
              <option value="all">全部历史</option>
              <option value="1">最近 1 小时</option>
              <option value="24">最近 24 小时</option>
            </select>
          </label>
        )}
        <QueryState
          error={query.error}
          loading={query.isPending}
          retry={() => void query.refetch()}
        />
        {query.data && !filtered.length && (
          <StatePanel kind="EMPTY">
            没有匹配记录。调整筛选或创建本地模拟数据。
          </StatePanel>
        )}
        {pageKey === "approvals" ? (
          <div className="approval-grid">
            {filtered.slice(page * 4, page * 4 + 4).map((r) => (
              <RiskApprovalPanel
                key={r.id}
                approval={r.data as Schema<"Approval">}
                task={taskQuery.data?.items.find(
                  (t) => t.id === (r.data as Schema<"Approval">).task_id,
                )}
                onDecide={
                  connected &&
                  !boot.error &&
                  boot.data?.app_mode === "LOCAL_MOCK" &&
                  boot.data.features.approvals?.status === "MOCK_ONLY"
                    ? (reject) =>
                        setDecision({
                          approval: r.data as Schema<"Approval">,
                          reject,
                        })
                    : undefined
                }
              />
            ))}
          </div>
        ) : (
          <ListTable
            rows={filtered.slice(page * 4, page * 4 + 4)}
            onSelect={setSelected}
          />
        )}
        <CursorPagination
          page={page}
          total={filtered.length}
          setPage={setPage}
        />
        <div className="row">
          {cursor && (
            <button
              onClick={() => {
                setCursor(undefined);
                setPage(0);
              }}
            >
              返回首批
            </button>
          )}
          {query.data?.next_cursor && (
            <button
              onClick={() => {
                setCursor(query.data?.next_cursor ?? undefined);
                setPage(0);
              }}
            >
              读取下一批
            </button>
          )}
        </div>
      </section>
      {"source_meta" in (query.data ?? {}) && (
        <ProvenanceTooltip
          meta={(query.data as Schema<"DisplayRecordList">).source_meta}
        />
      )}
      {pageKey === "services" && (
        <p className="muted">
          Cherry Studio 保留原有静态入口；本应用不读取、不探测、不调用。
        </p>
      )}
      {pageKey === "agents" && (
        <p className="muted">
          Agent Identity 与模型供应商不同。未授权调用保持禁用。
        </p>
      )}
      {selected && (
        <ConfirmationDialog
          title={selected.title}
          onClose={() => setSelected(null)}
          onConfirm={() => setSelected(null)}
        >
          <KeyValues value={selected.data} />
          {"source_meta" in selected.data && (
            <ProvenanceTooltip
              meta={(selected.data as Schema<"DisplayRecord">).source_meta}
            />
          )}
          <p>只读记录 · 不执行旧业务或下载私有文件</p>
        </ConfirmationDialog>
      )}
      {create && <CreateTask onClose={() => setCreate(false)} />}
      {decision && (
        <ConfirmationDialog
          title={decision.reject ? "确认演示拒绝" : "确认演示批准"}
          onClose={() => setDecision(null)}
          onConfirm={() => approvalMutation.mutate()}
          pending={approvalMutation.isPending}
        >
          <RiskApprovalPanel
            approval={decision.approval}
            task={taskQuery.data?.items.find(
              (t) => t.id === decision.approval.task_id,
            )}
          />
          <p>仅本地账本。批准后由纯合成 Worker 更新状态。</p>
          {approvalMutation.error && (
            <p role="alert" className="error-text">
              {approvalMutation.error.message}
            </p>
          )}
        </ConfirmationDialog>
      )}
      {notice && (
        <div className="toast" role="status" onClick={() => setNotice("")}>
          {notice}
        </div>
      )}
    </>
  );
}
export function ListTable({
  rows,
  onSelect,
}: {
  rows: Row[];
  onSelect: (r: Row) => void;
}) {
  return (
    <div className="list-table" role="table" aria-label="目录记录">
      <div className="table-head" role="row">
        <span role="columnheader">名称 / 标识</span>
        <span role="columnheader">状态</span>
        <span role="columnheader">归属 / 来源</span>
        <span role="columnheader">详情</span>
      </div>
      {rows.map((r) => (
        <div className="table-row" role="row" key={r.id}>
          <div role="cell">
            <strong>{r.title}</strong>
            <small>{r.id}</small>
          </div>
          <div role="cell">
            <HealthBadge value={r.status} />
            {"stale" in r.data && Boolean(r.data.stale) && (
              <HealthBadge value="STALE" />
            )}
          </div>
          <span role="cell" className="muted">
            {r.owner}
          </span>
          <span role="cell">
            {r.detail ? (
              <Link className="button small" to={r.detail}>
                查看 <ArrowUpRight size={14} />
              </Link>
            ) : (
              <button className="small" onClick={() => onSelect(r)}>
                查看记录
              </button>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}
function CreateTask({ onClose }: { onClose: () => void }) {
  const [title, setTitle] = useState("本地演示任务"),
    [error, setError] = useState(""),
    [outcome, setOutcome] = useState<string>(
      API_MODE === "mock" ? control.outcome : "SUCCEEDED",
    );
  const key = useRef(crypto.randomUUID()),
    workItem = useRef<string | null>(null),
    nav = useNavigate(),
    qc = useQueryClient();
  const mutation = useMutation({
    mutationFn: async () => {
      if (!title.trim()) throw Error("请输入标题");
      if (!workItem.current) {
        const w = required(
          await api.POST("/api/v1/work-items", {
            body: { title, kind: "task", source_system: "LOCAL MOCK" },
          }),
        );
        workItem.current = w.id;
      }
      return required(
        await api.POST("/api/v1/tasks", {
          params: { header: { "Idempotency-Key": key.current } },
          body: {
            work_item_id: workItem.current,
            capability: "local.simulate",
            resource_id: "local-ledger",
            arguments: { outcome },
            dry_run: true,
            origin: { channel: "web", source_ref: "local-demo" },
          },
        }),
      );
    },
    onSuccess: (r) => {
      void qc.invalidateQueries();
      nav(`/tasks/${r.task_id}`);
      onClose();
    },
    onError: (e) => setError(e.message),
  });
  return (
    <ConfirmationDialog
      title="新建本地模拟任务"
      onClose={onClose}
      onConfirm={() => mutation.mutate()}
      pending={mutation.isPending}
    >
      <p>LOCAL MOCK · MEDIUM · 仅新平台本地账本</p>
      <label className="field">
        工作项标题
        <input
          maxLength={200}
          disabled={mutation.isPending}
          value={title}
          onChange={(e) => {
            setTitle(e.target.value);
            workItem.current = null;
            key.current = crypto.randomUUID();
          }}
        />
      </label>
      <label className="field">
        模拟任务结果
        <select
          aria-label="模拟任务结果"
          disabled={mutation.isPending}
          value={outcome}
          onChange={(e) => {
            setOutcome(e.target.value);
            key.current = crypto.randomUUID();
          }}
        >
          <option>SUCCEEDED</option>
          <option>FAILED</option>
          <option>NEEDS_RECONCILIATION</option>
        </select>
      </label>
      <KeyValues
        value={{
          capability: "local.simulate",
          target: "local-ledger",
          arguments: JSON.stringify({ outcome }),
          dry_run: true,
          idempotency_key: key.current,
        }}
      />
      <p>失败重试保留幂等键；不会调用模型、旧服务或真实 Worker。</p>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
    </ConfirmationDialog>
  );
}

const detailTabs = {
  tasks: ["Overview", "Attempts", "Events", "Approvals", "Artifacts"],
  nodes: ["Health", "Services", "Network", "History", "Risk"],
  services: ["Runtime", "Dependencies", "Logs", "Owner", "Changes"],
  agents: ["Identity", "Capabilities", "Runtime", "Tasks", "Source"],
} as const;
export function DetailPage({ kind }: { kind: keyof typeof detailTabs }) {
  const connected = useConnection();
  const { id = "" } = useParams(),
    [tab, setTab] = useState<string>(detailTabs[kind][0]),
    [cancel, setCancel] = useState(false),
    [notice, setNotice] = useState(""),
    qc = useQueryClient(),
    boot = useBootstrap();
  const connection = useEvents();
  useEffect(() => setTab(detailTabs[kind][0]), [kind, id]);
  const query = useQuery({
    queryKey: ["detail", kind, id],
    queryFn: async () => {
      const params = { path: { id } };
      switch (kind) {
        case "tasks":
          return required(await api.GET("/api/v1/tasks/{id}", { params }));
        case "nodes":
          return required(await api.GET("/api/v1/nodes/{id}", { params }));
        case "services": {
          const r = required(
            await api.GET("/api/v1/resources/{id}", { params }),
          );
          if (r.kind !== "service") throw Error("资源类型不匹配");
          return r;
        }
        case "agents":
          return required(await api.GET("/api/v1/agents/{id}", { params }));
      }
    },
    refetchInterval: kind === "tasks" ? 1500 : false,
    refetchIntervalInBackground: false,
  });
  const related = useQuery({
    queryKey: ["related", kind, id, tab],
    enabled: !!query.data,
    queryFn: async () => {
      if (kind === "tasks") {
        if (tab === "Events")
          return required(
            await api.GET("/api/v1/tasks/{id}/events", {
              params: { path: { id } },
            }),
          ).items;
        if (tab === "Attempts")
          return required(
            await api.GET("/api/v1/tasks/{id}/attempts", {
              params: { path: { id } },
            }),
          ).items;
        if (tab === "Approvals")
          return (await readCatalog.approvals()).items.filter(
            (a) => a.task_id === id,
          );
        if (tab === "Artifacts")
          return (await readCatalog.artifacts()).items.filter(
            (a) => a.task_id === id,
          );
      }
      if (kind === "nodes") {
        if (tab === "Services")
          return (await readCatalog.services()).items.filter(
            (r) => r.node_id === id,
          );
        if (tab === "Network") return (await readCatalog.network()).items;
        if (tab === "History")
          return required(await api.GET("/api/v1/events/history")).items.filter(
            (e) => e.resource_ref === id,
          );
      }
      if (kind === "services" && tab === "Logs")
        return required(await api.GET("/api/v1/observations")).items.filter(
          (o) => o.resource_id === id,
        );
      if (kind === "services" && tab === "Changes")
        return required(await api.GET("/api/v1/audit")).items.filter(
          (e) => e.resource_ref === id,
        );
      if (kind === "agents" && tab === "Capabilities") {
        const a = query.data as Schema<"Agent">;
        return required(await api.GET("/api/v1/capabilities")).items.filter(
          (c) => a.capabilities.includes(c.name),
        );
      }
      if (kind === "agents" && tab === "Tasks") return [];
      return [];
    },
    refetchInterval: kind === "tasks" ? 1500 : false,
    refetchIntervalInBackground: false,
  });
  const mutation = useMutation({
    mutationFn: () =>
      api.POST("/api/v1/tasks/{id}/cancel", { params: { path: { id } } }),
    onSuccess: () => {
      setCancel(false);
      setNotice("LOCAL MOCK · 已取消");
      void qc.invalidateQueries();
    },
    onError: (e) => setNotice(e.message),
  });
  const entity = denied(query.error) ? undefined : query.data,
    task = kind === "tasks" ? (entity as Schema<"Task">) : null;
  const title = entity
    ? "display_name" in entity
      ? entity.display_name
      : "name" in entity
        ? entity.name
        : "capability" in entity
          ? entity.capability
          : id
    : "记录详情";
  return (
    <>
      <Link className="back-link" to={`/${kind}`}>
        ← 返回{pages.find((p) => p[0] === kind)?.[1]}
      </Link>
      <PageHeader
        kicker={`${kind} / DETAIL`}
        title={title}
        description="LOCAL MOCK · 对象详情与关联记录"
      >
        <HealthBadge value={task?.state ?? "UNKNOWN"} />
        {task &&
          connected &&
          !boot.error &&
          boot.data?.app_mode === "LOCAL_MOCK" &&
          ["WAITING_APPROVAL", "QUEUED"].includes(task.state) && (
            <button onClick={() => setCancel(true)}>取消模拟任务</button>
          )}
      </PageHeader>
      <QueryState
        error={query.error}
        loading={query.isPending}
        retry={() => void query.refetch()}
      />
      {entity && (
        <>
          <div className="meta-strip">
            <span>LOCAL MOCK</span>
            <span>{connection}</span>
            <span>缓存不会升级写权限</span>
          </div>
          <EntityDetailTabs tabs={detailTabs[kind]} tab={tab} setTab={setTab} />
          <section
            id="entity-detail-panel"
            className="panel detail-body"
            role="tabpanel"
            tabIndex={0}
            aria-labelledby={`detail-tab-${tab}`}
          >
            <h2>{tab}</h2>
            {tab === detailTabs[kind][0] ? (
              <>
                <KeyValues value={entity} />
                {task && (
                  <Link className="button primary" to="/approvals">
                    前往本地模拟审批 ↗
                  </Link>
                )}
              </>
            ) : (kind === "services" && tab === "Owner") ||
              (kind === "agents" && tab === "Source") ||
              (kind === "nodes" && tab === "Risk") ? null : kind === "agents" &&
              tab === "Runtime" ? (
              <KeyValues
                value={{
                  runtime_node_id:
                    (entity as Schema<"Agent">).runtime_node_id ?? null,
                  status: (entity as Schema<"Agent">).status,
                  source_mode: "MOCK · catalog only",
                }}
              />
            ) : related.isPending ? (
              <StatePanel kind="LOADING" />
            ) : related.error ? (
              <StatePanel kind="ERROR">{related.error.message}</StatePanel>
            ) : related.data?.length ? (
              kind === "tasks" && tab === "Events" ? (
                <TaskTimeline events={related.data as Schema<"TaskEvent">[]} />
              ) : (
                related.data.map((v, i) => (
                  <article className="related-record" key={i}>
                    <KeyValues value={v} />
                  </article>
                ))
              )
            ) : (
              <StatePanel kind="UNKNOWN">
                暂无可靠的 {tab}{" "}
                记录。未连接真实数据源，不能推断依赖或运行状态。
              </StatePanel>
            )}
            {kind === "agents" && tab === "Source" && (
              <KeyValues
                value={{
                  owner_system: (entity as Schema<"Agent">).owner_system,
                  source_mode: "MOCK",
                  observed_at: (entity as Schema<"Agent">).observed_at ?? null,
                }}
              />
            )}
            {kind === "services" && tab === "Owner" && (
              <KeyValues
                value={{
                  owner_system: (entity as Schema<"Resource">).owner_system,
                  node_id: (entity as Schema<"Resource">).node_id,
                }}
              />
            )}
            {kind === "nodes" && tab === "Risk" && (
              <p>只读备用不接管写主控；生产探针与高风险操作禁用。</p>
            )}
          </section>
        </>
      )}
      {cancel && (
        <ConfirmationDialog
          title="取消本地模拟任务"
          onClose={() => setCancel(false)}
          onConfirm={() => mutation.mutate()}
          pending={mutation.isPending}
        >
          <p>仅改变新平台模拟任务账本，不影响现有业务。</p>
          {mutation.error && (
            <p role="alert" className="error-text">
              {mutation.error.message}
            </p>
          )}
        </ConfirmationDialog>
      )}
      {notice && (
        <div className="toast" role="status">
          {notice}
        </div>
      )}
    </>
  );
}
