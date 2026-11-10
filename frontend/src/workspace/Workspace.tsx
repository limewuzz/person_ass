import { useEffect, useRef, useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  CircleHelp,
  FileText,
  Lightbulb,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import {
  api,
  ApiError,
  API_WRITES_ALLOWED,
  required,
  type Schema,
} from "../api/client";
import { useConnection } from "../app/connection";
import {
  ConfirmationDialog,
  KeyValues,
  ProvenanceTooltip,
  QueryState,
} from "../components/ui";
import { useBootstrap } from "../features/pages";
import {
  collectPages,
  draftKey,
  exportRecord,
  journalKey,
  performVerifiedDownload,
  performVerifiedUpload,
  readDraft,
  readSubmission,
  submitConversationMessage,
  submitWork,
  syncWorkspaceCrossDevice,
  taskStates,
  terminal,
  type Submission,
} from "./model";
import "./workspace.css";

const readWorks = () =>
  collectPages(async (cursor) =>
    required(
      await api.GET("/api/v1/work-items", { params: { query: { cursor } } }),
    ),
  );
const readTasks = () =>
  collectPages(async (cursor) =>
    required(await api.GET("/api/v1/tasks", { params: { query: { cursor } } })),
  );
const readApprovals = () =>
  collectPages(async (cursor) =>
    required(
      await api.GET("/api/v1/approvals", { params: { query: { cursor } } }),
    ),
  );
const readArtifacts = () =>
  collectPages(async (cursor) =>
    required(
      await api.GET("/api/v1/artifacts", { params: { query: { cursor } } }),
    ),
  );
function useWorks() {
  return useQuery({ queryKey: ["workspace", "works"], queryFn: readWorks });
}
function useTasks() {
  return useQuery({ queryKey: ["workspace", "tasks"], queryFn: readTasks });
}
function errorDenies(error: Error | null) {
  return error instanceof ApiError && [401, 403, 404].includes(error.status);
}
function useWriteGate() {
  const boot = useBootstrap(),
    connected = useConnection();
  return {
    boot,
    connected,
    allowed:
      API_WRITES_ALLOWED &&
      connected &&
      !boot.error &&
      boot.data?.app_mode === "LOCAL_MOCK" &&
      boot.data.features.tasks?.status === "MOCK_ONLY",
  };
}
function TaskStatus({ state }: { state: Schema<"Task">["state"] }) {
  return (
    <span
      className={`ws-status ws-status-${state.toLowerCase()}`}
      data-state={state}
    >
      {taskStates[state]}
    </span>
  );
}
function DateLabel({ value }: { value: string }) {
  return (
    <time dateTime={value}>
      {new Date(value).toLocaleString("zh-CN", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })}
    </time>
  );
}
function Empty({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="ws-empty">
      <div className="ws-empty-icon">
        <Sparkles size={25} />
      </div>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
function Title({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <header className="ws-page-title">
      <div>
        <span className="ws-eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children}
    </header>
  );
}

export function WorkspaceLayout() {
  const { boot, connected } = useWriteGate(),
    location = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  return (
    <div className="workspace">
      <a className="skip-link" href="#workspace-main">
        跳到主要内容
      </a>
      <header className="ws-topbar">
        <Link to="/" className="ws-brand">
          <span className="ws-mark">
            m<span>✦</span>
          </span>
          <span>
            MagicWorkshop<small>你的个人工作坊</small>
          </span>
        </Link>
        <nav aria-label="工作坊导航">
          <NavLink to="/" end>
            开始
          </NavLink>
          <NavLink to="/workbench/history">我的工作</NavLink>
          <NavLink to="/workbench/results">结果库</NavLink>
          <NavLink to="/workbench/assistants">助手</NavLink>
        </nav>
        <Link className="ws-admin-link" to="/dashboard">
          管理后台 <ArrowRight size={14} />
        </Link>
      </header>
      <div className="ws-runtime" role="status">
        <ShieldCheck size={14} />
        {!connected
          ? "连接已中断 · 缓存只读，恢复后请刷新"
          : !API_WRITES_ALLOWED
            ? "只读发布 · 已授权记录可查看，执行入口尚未开放"
            : boot.data?.app_mode === "LOCAL_MOCK"
              ? "本地演示空间 · 操作仅在模拟账本中进行"
              : "当前执行入口未开放 · 可查看已授权记录"}
        <span className="ws-source">
          {boot.error
            ? "UNAVAILABLE"
            : (boot.data?.source_meta.data_mode ?? "UNKNOWN")}
        </span>
      </div>
      <main id="workspace-main" className="ws-main" tabIndex={-1}>
        {errorDenies(boot.error) ? (
          <QueryState
            error={boot.error}
            loading={false}
            retry={() => void boot.refetch()}
          />
        ) : (
          <Outlet />
        )}
      </main>
      <footer className="ws-footer">
        <span>把想法变成有迹可循的工作。</span>
        <Link to="/architecture">
          了解工作坊架构 <ArrowRight size={13} />
        </Link>
      </footer>
    </div>
  );
}

export function WorkspaceHome() {
  const [draft, setDraft] = useState(readDraft),
    [submission, setSubmission] = useState(readSubmission),
    [confirm, setConfirm] = useState(false),
    [ack, setAck] = useState(false),
    [storageError, setStorageError] = useState(false),
    [notice, setNotice] = useState("");
  const gate = useWriteGate(),
    works = useWorks(),
    tasks = useTasks(),
    nav = useNavigate(),
    qc = useQueryClient(),
    flight = useRef(false);
  const caps = useQuery({
    queryKey: ["workspace", "capabilities"],
    queryFn: async () => required(await api.GET("/api/v1/capabilities")),
  });
  const [uploadedArtifact, setUploadedArtifact] =
    useState<Schema<"Artifact"> | null>(null);
  const syncQuery = useQuery({
    queryKey: ["workspace", "client-sync"],
    queryFn: async () => required(await api.GET("/api/v1/clients/sync")),
  });
  const syncMutation = useMutation({
    mutationFn: async () => {
      required(
        await api.POST("/api/v1/clients/devices", {
          body: {
            device_id: "web-workspace-primary",
            platform: "web",
            app_version: "2.0.0-rc1",
            os_arch: "browser-wasm",
            keystore_kind: "web_httponly_cookie",
          },
        }),
      );
      return await syncWorkspaceCrossDevice(
        "web-workspace-primary",
        draft.title.trim()
          ? [{ title: draft.title.trim(), kind: draft.kind }]
          : [],
        { theme: "system", locale: "zh-CN" },
        async () => required(await api.GET("/api/v1/clients/sync")),
        async (body) =>
          required(await api.POST("/api/v1/clients/sync", { body })),
      );
    },
    onSuccess: () =>
      void qc.invalidateQueries({ queryKey: ["workspace", "client-sync"] }),
  });
  const uploadMutation = useMutation({
    mutationFn: async (input: {
      name: string;
      mime: string;
      content: string;
    }) => {
      const bytes = new TextEncoder().encode(input.content);
      return await performVerifiedUpload(
        input.name,
        input.mime,
        bytes,
        async (body) =>
          required(await api.POST("/api/v1/uploads/tickets", { body })),
        async (ticketId, body) =>
          required(
            await api.PUT("/api/v1/uploads/{ticket_id}", {
              params: { path: { ticket_id: ticketId } },
              body,
            }),
          ),
      );
    },
    onSuccess: (art) => {
      setUploadedArtifact(art);
      void qc.invalidateQueries({ queryKey: ["workspace", "artifacts"] });
    },
  });
  const localEnabled = caps.data?.items.some(
    (c) => c.name === "local.simulate" && c.enabled && c.risk === "MEDIUM",
  );
  const writable = gate.allowed && !caps.error && !!localEnabled;
  const locked = !!submission && submission.stage !== "ready";
  useEffect(() => {
    try {
      sessionStorage.setItem(draftKey, JSON.stringify(draft));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }, [draft]);
  const save = (s: Submission) => {
    sessionStorage.setItem(journalKey, JSON.stringify(s));
    setSubmission(s);
  };
  const mutation = useMutation({
    mutationFn: async () => {
      if (!writable || !ack) throw Error("请先确认当前空间的操作范围。");
      if (flight.current) throw Error("提交正在进行，请勿重复操作。");
      flight.current = true;
      try {
        const snapshot = submission ?? {
          ...draft,
          title: draft.title.trim(),
          key: crypto.randomUUID(),
          stage: "ready" as const,
        };
        if (!snapshot.title.trim()) throw Error("请写下你想完成的事。");
        save(snapshot);
        return await submitWork(
          snapshot,
          save,
          async (body) =>
            required(await api.POST("/api/v1/work-items", { body })),
          async (body, key) =>
            required(
              await api.POST("/api/v1/tasks", {
                body,
                params: { header: { "Idempotency-Key": key } },
              }),
            ),
        );
      } finally {
        flight.current = false;
      }
    },
    onSuccess: (s) => {
      sessionStorage.removeItem(journalKey);
      sessionStorage.removeItem(draftKey);
      setSubmission(null);
      setDraft({ title: "", kind: "task", outcome: "SUCCEEDED" });
      void qc.invalidateQueries();
      setConfirm(false);
      nav(s.taskId ? `/workbench/tasks/${s.taskId}` : "/workbench/history");
    },
  });
  const recent = errorDenies(tasks.error) ? [] : (tasks.data ?? []).slice(0, 3),
    recentWorks = errorDenies(works.error) ? [] : (works.data ?? []);
  return (
    <>
      <div className="ws-home-title">
        <span className="ws-eyebrow">
          <span className="ws-dot" /> YOUR PERSONAL WORKSHOP
        </span>
        <h1>
          今天，想把什么
          <br />
          <span>交给工作坊？</span>
        </h1>
        <p>
          写下一个目标，把过程交给工作流。每一次确认、进展和结果，都有地方可找。
        </p>
      </div>
      <section className="ws-composer" aria-label="发起工作">
        <div className="ws-compose-tabs" role="group" aria-label="工作类型">
          {(
            [
              ["task", "任务", Sparkles],
              ["idea", "想法", Lightbulb],
              ["paper", "研究笔记", FileText],
            ] as const
          ).map(([kind, label, Icon]) => (
            <button
              key={kind}
              aria-pressed={draft.kind === kind}
              disabled={locked || mutation.isPending}
              onClick={() => setDraft({ ...draft, kind })}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>
        <label className="ws-sr-only" htmlFor="work-request">
          你想完成的事
        </label>
        <textarea
          id="work-request"
          maxLength={200}
          value={draft.title}
          disabled={locked || mutation.isPending}
          onChange={(e) => setDraft({ ...draft, title: e.target.value })}
          placeholder={
            draft.kind === "task"
              ? "例如：为一个新想法走一遍任务、确认和结果流程…"
              : "记下想法或研究标题，先保存，稍后继续。"
          }
        />
        <div className="ws-composer-bottom">
          <span>{draft.title.length} / 200 · 草稿保留在当前会话</span>
          <button
            className="ws-primary"
            disabled={
              !draft.title.trim() ||
              !writable ||
              storageError ||
              mutation.isPending ||
              locked
            }
            onClick={() => {
              setAck(false);
              mutation.reset();
              setConfirm(true);
            }}
          >
            {draft.kind === "task" ? "检查并发起" : "保存到我的工作"}
            <ArrowRight size={17} />
          </button>
        </div>
        <div className="ws-composer-context">
          <span>
            <span className="ws-dot" />{" "}
            {draft.kind === "task"
              ? "本地流程助手 · 模拟执行"
              : "仅保存记录 · 不自动执行"}
          </span>
          <span>
            <CircleHelp size={13} /> 文件上传与真实模型对话尚未接入
          </span>
        </div>
      </section>
      {storageError && (
        <div className="ws-notice" role="alert">
          当前浏览器无法保存会话草稿。为避免丢失提交状态，已暂停发起。
        </div>
      )}
      {!writable && (
        <div className="ws-notice" role="status">
          {!gate.connected
            ? "离线期间可查看缓存，发起和授权暂不可用。"
            : !API_WRITES_ALLOWED
              ? "当前发布为只读模式，可浏览历史与结果；任务执行尚未开放。"
              : "当前未获得本地任务能力，或身份/能力数据不可用；发起入口已锁定。"}
          <button
            onClick={() => {
              void gate.boot.refetch();
              void caps.refetch();
            }}
          >
            重新检查
          </button>
        </div>
      )}
      {submission && (
        <section className="ws-notice" role="alert">
          <div>
            <strong>有一份未完成的提交</strong>
            <p>{submission.title}</p>
            <p>
              {submission.stage === "unknown-work" ||
              submission.stage === "creating-work"
                ? "工作项提交结果未知。请先核对历史，不能直接重复创建。"
                : "工作项已保存。继续提交会沿用同一任务幂等键和原始内容。"}
            </p>
          </div>
          <div className="ws-actions">
            <Link to="/workbench/history">核对历史</Link>
            {submission.stage !== "unknown-work" &&
              submission.stage !== "creating-work" && (
                <button
                  disabled={!writable}
                  onClick={() => {
                    setAck(false);
                    setConfirm(true);
                  }}
                >
                  继续这份提交
                </button>
              )}
            <button onClick={() => setNotice("clear-journal")}>
              清除提交记录
            </button>
          </div>
        </section>
      )}
      <section className="ws-panel" aria-label="多端状态同步与附件上传">
        <div className="ws-section-title">
          <h2>多端状态同步与附件上传（V2）</h2>
          <span>
            同步游标：{syncQuery.data?.cursor ?? "sync-cursor-0"}（版本{" "}
            {syncQuery.data?.revision ?? 0}）
          </span>
        </div>
        <div className="ws-actions">
          <button
            disabled={!writable || syncMutation.isPending}
            onClick={() => syncMutation.mutate()}
          >
            <RefreshCw size={14} />
            同步当前草稿到多端
          </button>
          <button
            disabled={!writable || uploadMutation.isPending}
            onClick={() =>
              uploadMutation.mutate({
                name: "workspace-note.md",
                mime: "text/markdown",
                content: `# ${draft.title || "MagicWorkshop Note"}\nCreated in V2 Workspace.`,
              })
            }
          >
            <Plus size={14} />
            上传验证附件（SHA-256）
          </button>
          {uploadedArtifact && (
            <span className="ws-tag">
              已登记附件：{uploadedArtifact.id.slice(0, 8)}（SHA-256 已核验）
            </span>
          )}
        </div>
      </section>
      <div className="ws-home-grid">
        <section>
          <div className="ws-section-title">
            <h2>从这里开始</h2>
            <span>一个清晰的小目标，就够了</span>
          </div>
          <div className="ws-starters">
            {[
              ["task", "走通一个任务", "体验发起、授权和结果追踪。", Sparkles],
              ["idea", "留住一个想法", "先记下来，让灵感有处安放。", Lightbulb],
              ["paper", "建立研究笔记", "把下一次阅读放进工作清单。", FileText],
            ].map(([kind, title, desc, Icon]) => {
              const I = Icon as typeof Sparkles;
              return (
                <button
                  key={String(kind)}
                  disabled={locked}
                  onClick={() => {
                    setDraft({
                      ...draft,
                      kind: kind as typeof draft.kind,
                      title: String(title),
                    });
                    document.getElementById("work-request")?.focus();
                  }}
                >
                  <I size={20} />
                  <strong>{String(title)}</strong>
                  <span>{String(desc)}</span>
                  <ArrowRight size={16} />
                </button>
              );
            })}
          </div>
        </section>
        <aside className="ws-how">
          <span className="ws-eyebrow">HOW IT WORKS</span>
          <h2>你掌握每一步。</h2>
          <ol>
            <li>
              <span>01</span>
              <div>
                <strong>说清目标</strong>
                <p>保存为工作项，留下一条起点。</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>确认再推进</strong>
                <p>需要授权时，先查看范围与风险。</p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>回来取结果</strong>
                <p>过程、产物登记与历史放在一起。</p>
              </div>
            </li>
          </ol>
        </aside>
      </div>
      <section className="ws-recent">
        <div className="ws-section-title">
          <h2>最近在做</h2>
          <Link to="/workbench/history">
            查看全部 <ArrowRight size={14} />
          </Link>
        </div>
        <QueryState
          error={tasks.error ?? works.error}
          loading={tasks.isPending || works.isPending}
          retry={() => {
            void tasks.refetch();
            void works.refetch();
          }}
        />
        {recent.length > 0 ? (
          <div className="ws-cards">
            {recent.map((t) => (
              <TaskCard
                key={t.id}
                task={t}
                title={recentWorks.find((w) => w.id === t.work_item_id)?.title}
              />
            ))}
          </div>
        ) : (
          !tasks.isPending &&
          !tasks.error && (
            <Empty title="第一份工作，从一个想法开始">
              在上方写下目标，这里会记录接下来的进展。
            </Empty>
          )
        )}
      </section>
      {confirm && (
        <ConfirmationDialog
          confirmLabel={
            (submission?.kind ?? draft.kind) === "task"
              ? "确认发起"
              : "确认保存"
          }
          confirmDisabled={!ack || !writable}
          title={draft.kind === "task" ? "确认这份工作" : "确认保存记录"}
          pending={mutation.isPending}
          onClose={() => {
            if (!mutation.isPending) setConfirm(false);
          }}
          onConfirm={() => mutation.mutate()}
        >
          <h3>{submission?.title ?? draft.title}</h3>
          <p>
            {(submission?.kind ?? draft.kind) === "task"
              ? "将保存工作项，并创建一条需要确认的本地模拟任务。执行只作用于新模拟账本，不调用真实模型、探针或旧业务。"
              : "仅保存这条想法或研究记录，不创建执行任务。"}
          </p>
          {(submission?.kind ?? draft.kind) === "task" && (
            <details>
              <summary>演示选项</summary>
              <label className="field">
                模拟结果
                <select
                  aria-label="前台模拟结果"
                  disabled={locked || mutation.isPending}
                  value={draft.outcome}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      outcome: e.target.value as typeof draft.outcome,
                    })
                  }
                >
                  <option value="SUCCEEDED">成功</option>
                  <option value="FAILED">失败</option>
                  <option value="NEEDS_RECONCILIATION">失联后等待核对</option>
                </select>
              </label>
            </details>
          )}
          <label className="ws-check">
            <input
              type="checkbox"
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
            />
            我已了解范围，确认使用本地演示空间。
          </label>
          {!ack && <p className="muted">勾选范围确认后，才能提交。</p>}
          {mutation.error && (
            <p role="alert" className="error-text">
              {mutation.error.message}
            </p>
          )}
        </ConfirmationDialog>
      )}
      {notice === "clear-journal" && (
        <ConfirmationDialog
          title="清除本地提交记录？"
          onClose={() => setNotice("")}
          onConfirm={() => {
            sessionStorage.removeItem(journalKey);
            setSubmission(null);
            setNotice("");
            mutation.reset();
          }}
        >
          <p>
            这不会取消或删除服务端工作。请先在“我的工作”核对提交结果；清除后再次发起可能生成一份新工作。
          </p>
        </ConfirmationDialog>
      )}
    </>
  );
}

function TaskCard({ task, title }: { task: Schema<"Task">; title?: string }) {
  return (
    <Link className="ws-task-card" to={`/workbench/tasks/${task.id}`}>
      <div className="ws-card-top">
        <span className="ws-card-icon">
          <Sparkles size={19} />
        </span>
        <TaskStatus state={task.state} />
      </div>
      <h3>{title ?? task.capability}</h3>
      <p>
        {task.capability === "local.simulate"
          ? "本地流程演示"
          : "任务记录 · 执行能力以服务端策略为准"}
      </p>
      <div className="ws-card-bottom">
        <DateLabel value={task.updated_at} />
        <ArrowRight size={17} />
      </div>
    </Link>
  );
}

export function WorkspaceHistory() {
  const works = useWorks(),
    tasks = useTasks(),
    [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all"),
    [sort, setSort] = useState("newest");
  const denied = errorDenies(works.error) || errorDenies(tasks.error);
  const workItems = denied ? [] : (works.data ?? []),
    taskItems = denied ? [] : (tasks.data ?? []);
  const filtered = taskItems
    .filter((t) => {
      const text =
        (workItems.find((w) => w.id === t.work_item_id)?.title ??
          t.capability) + t.id;
      return (
        text.toLowerCase().includes(search.toLowerCase()) &&
        (filter === "all" ||
          (filter === "done"
            ? t.state === "SUCCEEDED"
            : filter === "attention"
              ? [
                  "FAILED",
                  "EXPIRED",
                  "NEEDS_RECONCILIATION",
                  "WAITING_APPROVAL",
                ].includes(t.state)
              : !terminal.has(t.state)))
      );
    })
    .sort(
      (a, b) =>
        (sort === "newest" ? -1 : 1) * a.created_at.localeCompare(b.created_at),
    );
  const standalone = workItems.filter(
    (w) =>
      !taskItems.some((t) => t.work_item_id === w.id) &&
      w.title.toLowerCase().includes(search.toLowerCase()),
  );
  return (
    <>
      <Title
        eyebrow="YOUR WORK"
        title="我的工作"
        description="继续未完成的事，也找回已经留下的记录。"
      >
        <Link className="ws-primary" to="/">
          <Plus size={16} />
          发起工作
        </Link>
      </Title>
      <div className="ws-toolbar">
        <label>
          <span className="ws-sr-only">搜索我的工作</span>
          <input
            placeholder="搜索标题或任务编号"
            aria-label="搜索我的工作"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <select
          aria-label="工作状态"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">全部任务</option>
          <option value="active">进行中</option>
          <option value="attention">需要关注</option>
          <option value="done">已完成</option>
        </select>
        <select
          aria-label="时间排序"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
        >
          <option value="newest">最近优先</option>
          <option value="oldest">最早优先</option>
        </select>
        <button
          aria-label="刷新我的工作"
          onClick={() => {
            void works.refetch();
            void tasks.refetch();
          }}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      <QueryState
        error={works.error ?? tasks.error}
        loading={works.isPending || tasks.isPending}
        retry={() => {
          void works.refetch();
          void tasks.refetch();
        }}
      />
      <div className="ws-cards">
        {filtered.map((t) => (
          <TaskCard
            key={t.id}
            task={t}
            title={workItems.find((w) => w.id === t.work_item_id)?.title}
          />
        ))}
      </div>
      {!works.isPending &&
        !tasks.isPending &&
        !works.error &&
        !tasks.error &&
        !filtered.length && (
          <Empty title={search ? "没有找到匹配的任务" : "还没有执行任务"}>
            你可以调整筛选，或回到开始页发起一份新工作。
          </Empty>
        )}
      {filter === "all" && standalone.length > 0 && (
        <section className="ws-saved">
          <div className="ws-section-title">
            <h2>已保存的想法与工作项</h2>
            <span>保存不会自动执行</span>
          </div>
          {standalone.map((w) => (
            <article key={w.id}>
              <FileText size={18} />
              <div>
                <h3>{w.title}</h3>
                <small>
                  {w.kind} · {w.status} · <DateLabel value={w.created_at} />
                </small>
              </div>
              <span className="ws-tag">已保存</span>
            </article>
          ))}
        </section>
      )}
    </>
  );
}

function ArtifactCard({ artifact }: { artifact: Schema<"Artifact"> }) {
  const [dlState, setDlState] = useState<string>("");
  const canDownloadContent =
    !!artifact.sha256 &&
    !artifact.uri.startsWith("http://") &&
    !artifact.uri.startsWith("https://");
  const handleDownload = async () => {
    setDlState("校验中…");
    try {
      const res = await performVerifiedDownload(
        artifact.id,
        async (id) =>
          required(
            await api.POST("/api/v1/artifacts/{id}/download-ticket", {
              params: { path: { id } },
            }),
          ),
        async (id, ticket) =>
          required(
            await api.GET("/api/v1/artifacts/{id}/content", {
              params: { path: { id } },
              headers: { "X-Download-Ticket": ticket },
            }),
          ),
      );
      const objectUrl = URL.createObjectURL(
        new Blob([new Uint8Array(res.bytes)], { type: res.mimeType }),
      );
      const link = document.createElement("a");
      link.href = objectUrl;
      const proposedName = /filename="([A-Za-z0-9._-]+)"/.exec(
        res.disposition,
      )?.[1];
      link.download = proposedName ?? `${artifact.id}.bin`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      setDlState(`SHA-256 已核验 (${res.bytes.length} B)`);
    } catch (e) {
      setDlState(e instanceof Error ? e.message : "下载失败");
    }
  };
  return (
    <article className="ws-artifact">
      <FileText size={23} />
      <div>
        <h3>产物登记</h3>
        <p>{artifact.storage_system}</p>
        <code>{artifact.uri}</code>
        <small>
          SHA-256：{artifact.sha256 ?? "未提供"} · 大小：
          {artifact.byte_size ?? "未知"}
        </small>
        {dlState && <small role="status"> · {dlState}</small>}
      </div>
      {canDownloadContent ? (
        <button className="ws-secondary" onClick={() => void handleDownload()}>
          <ArrowDownToLine size={14} />
          受控下载
        </button>
      ) : (
        <span className="ws-tag">元数据</span>
      )}
    </article>
  );
}
export function WorkspaceResults() {
  const q = useQuery({
      queryKey: ["workspace", "artifacts"],
      queryFn: readArtifacts,
    }),
    tasks = useTasks(),
    works = useWorks(),
    [search, setSearch] = useState("");
  const hidden =
    errorDenies(q.error) ||
    errorDenies(tasks.error) ||
    errorDenies(works.error);
  const items = hidden
    ? []
    : (q.data ?? []).filter((a) =>
        `${a.uri} ${a.storage_system} ${works.data?.find((w) => w.id === tasks.data?.find((t) => t.id === a.task_id)?.work_item_id)?.title ?? ""}`
          .toLowerCase()
          .includes(search.toLowerCase()),
      );
  return (
    <>
      <Title
        eyebrow="YOUR OUTPUTS"
        title="结果库"
        description="每一份结果，都能回到产生它的那次工作。"
      >
        <button onClick={() => void q.refetch()}>
          <RefreshCw size={15} />
          刷新
        </button>
      </Title>
      <div className="ws-notice">
        <CircleHelp size={18} />
        <span>
          当前接口提供产物位置与校验信息，不提供文件内容。这里不会自动打开、预取或下载外部文件；任务记录可在详情中导出。
        </span>
      </div>
      <div className="ws-toolbar">
        <input
          aria-label="搜索结果"
          placeholder="按工作标题、位置或来源搜索"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <QueryState
        error={q.error ?? tasks.error ?? works.error}
        loading={q.isPending}
        retry={() => {
          void q.refetch();
          void tasks.refetch();
          void works.refetch();
        }}
      />
      <div className="ws-results">
        {items.map((a) => (
          <section key={a.id}>
            <ArtifactCard artifact={a} />
            {a.task_id && (
              <Link to={`/workbench/tasks/${a.task_id}`}>
                查看来源任务 <ArrowRight size={14} />
              </Link>
            )}
          </section>
        ))}
      </div>
      {!q.isPending && !q.error && !items.length && (
        <Empty title={search ? "没有匹配的产物" : "结果会在这里相遇"}>
          完成任务后，如果服务端登记了产物，就会出现在这里。
        </Empty>
      )}
    </>
  );
}

export function WorkspaceAssistants() {
  const q = useQuery({
      queryKey: ["workspace", "agents"],
      queryFn: () =>
        collectPages(async (cursor) =>
          required(
            await api.GET("/api/v1/agents", { params: { query: { cursor } } }),
          ),
        ),
    }),
    gate = useWriteGate();
  const caps = useQuery({
    queryKey: ["workspace", "capabilities"],
    queryFn: async () => required(await api.GET("/api/v1/capabilities")),
  });
  const qc = useQueryClient();
  const [convInput, setConvInput] = useState("");
  const providers = useQuery({
    queryKey: ["workspace", "ai-providers"],
    queryFn: async () => required(await api.GET("/api/v1/ai/providers")),
  });
  const routing = useQuery({
    queryKey: ["workspace", "ai-routing"],
    queryFn: async () => required(await api.GET("/api/v1/ai/routing-policy")),
  });
  const convs = useQuery({
    queryKey: ["workspace", "conversations"],
    queryFn: async () => required(await api.GET("/api/v1/conversations")),
  });
  const convMutation = useMutation({
    mutationFn: async () => {
      if (!gate.allowed) throw Error("当前会话不能写入。");
      const content = convInput.trim();
      if (!content) throw Error("请输入对话内容。");
      const conversation = required(
        await api.POST("/api/v1/conversations", {
          body: { title: content.slice(0, 200) },
        }),
      );
      return submitConversationMessage(
        conversation.id,
        content,
        crypto.randomUUID(),
        false,
        async (id, body, key) =>
          required(
            await api.POST("/api/v1/conversations/{id}/messages", {
              params: { path: { id }, header: { "Idempotency-Key": key } },
              body,
            }),
          ),
      );
    },
    onSuccess: () => {
      setConvInput("");
      void qc.invalidateQueries({ queryKey: ["workspace", "conversations"] });
    },
  });
  const agents =
    errorDenies(q.error) || errorDenies(caps.error) ? [] : (q.data ?? []);
  return (
    <>
      <Title
        eyebrow="YOUR ASSISTANTS"
        title="认识工作坊的助手"
        description="先看清能力与状态，再决定把什么交给它。"
      />
      <div className="ws-notice">
        <ShieldCheck size={18} />
        <span>
          目录记录不代表模型已经在线。对话可保存到当前控制平面；模型执行仍受
          Dry-Run 和审批限制。
        </span>
      </div>
      <QueryState
        error={q.error ?? caps.error}
        loading={q.isPending || caps.isPending}
        retry={() => {
          void q.refetch();
          void caps.refetch();
        }}
      />
      <section className="ws-panel" aria-label="AI 路由与工作坊会话">
        <div className="ws-section-title">
          <h2>AI 模型路由与工作坊会话（V2）</h2>
          <span>
            默认路由：{routing.data?.default_model_id ?? "尚未配置"} ·{" "}
            已登记供应商：{providers.data?.items.length ?? 0}
          </span>
        </div>
        <div className="ws-toolbar">
          <input
            aria-label="发起新对话标题"
            placeholder="输入对话主题或向助手提问…"
            value={convInput}
            onChange={(e) => setConvInput(e.target.value)}
          />
          <button
            className="ws-primary"
            disabled={
              !gate.allowed || !convInput.trim() || convMutation.isPending
            }
            onClick={() => convMutation.mutate()}
          >
            发送并记录会话
          </button>
        </div>
        {convs.data?.items.length ? (
          <div className="ws-saved">
            {convs.data.items.slice(0, 5).map((c) => (
              <article key={c.id}>
                <Sparkles size={16} />
                <div>
                  <h3>{c.title}</h3>
                  <small>
                    消息数：{c.message_count} · 更新于{" "}
                    <DateLabel value={c.updated_at} />
                  </small>
                </div>
                <span className="ws-tag">{c.agent_id ?? "默认助手"}</span>
              </article>
            ))}
          </div>
        ) : null}
      </section>
      <QueryState
        error={
          providers.error ?? routing.error ?? convs.error ?? convMutation.error
        }
        loading={providers.isPending || routing.isPending || convs.isPending}
        retry={() => {
          void providers.refetch();
          void routing.refetch();
          void convs.refetch();
        }}
      />
      <div className="ws-cards">
        {agents.map((a) => {
          const canSimulate =
            gate.allowed &&
            !caps.error &&
            a.capabilities.includes("local.simulate") &&
            caps.data?.items.some(
              (c) => c.name === "local.simulate" && c.enabled,
            );
          return (
            <article className="ws-agent" key={a.id}>
              <div className="ws-agent-avatar">
                {a.display_name.slice(0, 1)}
              </div>
              <span className="ws-tag">{a.status}</span>
              <h2>{a.display_name}</h2>
              <p>
                {a.capabilities.length
                  ? a.capabilities.join(" · ")
                  : "暂无已登记能力"}
              </p>
              <small>{a.owner_system}</small>
              {canSimulate ? (
                <Link className="ws-secondary" to="/">
                  体验本地流程 <ArrowRight size={14} />
                </Link>
              ) : (
                <button disabled>执行能力未开放</button>
              )}
            </article>
          );
        })}
      </div>
      {!q.isPending && !q.error && !agents.length && (
        <Empty title="还没有可见的助手">
          稍后刷新，或前往管理后台查看目录配置。
        </Empty>
      )}
    </>
  );
}

export function WorkspaceTask() {
  const { id = "" } = useParams(),
    gate = useWriteGate(),
    qc = useQueryClient(),
    works = useWorks();
  const task = useQuery({
    queryKey: ["workspace", "task", id],
    queryFn: async () =>
      required(
        await api.GET("/api/v1/tasks/{id}", { params: { path: { id } } }),
      ),
    refetchInterval: (q) =>
      q.state.data && terminal.has(q.state.data.state) ? false : 1500,
    refetchIntervalInBackground: false,
  });
  const state = task.data?.state;
  const related = useQuery({
    queryKey: ["workspace", "related", id, state],
    enabled: !!task.data && !errorDenies(task.error),
    queryFn: async () => {
      const [events, attempts, approvals, artifacts] = await Promise.all([
        collectPages(async (cursor) =>
          required(
            await api.GET("/api/v1/tasks/{id}/events", {
              params: { path: { id }, query: { cursor } },
            }),
          ),
        ),
        api
          .GET("/api/v1/tasks/{id}/attempts", { params: { path: { id } } })
          .then((r) => required(r).items),
        readApprovals(),
        readArtifacts(),
      ]);
      return {
        events,
        attempts,
        approvals: approvals.filter((a) => a.task_id === id),
        artifacts: artifacts.filter((a) => a.task_id === id),
      };
    },
    refetchInterval: state && !terminal.has(state) ? 1500 : false,
    refetchIntervalInBackground: false,
  });
  const [decision, setDecision] = useState<{
      approval: Schema<"Approval">;
      reject: boolean;
    } | null>(null),
    [cancel, setCancel] = useState(false),
    [notice, setNotice] = useState("");
  useEffect(() => {
    setDecision(null);
    setCancel(false);
    setNotice("");
  }, [id]);
  const mutation = useMutation({
    mutationFn: async () => {
      if (
        !gate.allowed ||
        gate.boot.data?.features.approvals?.status !== "MOCK_ONLY"
      )
        throw Error("当前身份或连接不允许授权。");
      if (cancel)
        return required(
          await api.POST("/api/v1/tasks/{id}/cancel", {
            params: { path: { id } },
          }),
        );
      if (
        !decision ||
        decision.approval.state !== "PENDING" ||
        decision.approval.risk !== "MEDIUM" ||
        Date.parse(decision.approval.expires_at) <= Date.now()
      )
        throw Error("授权已过期或状态变化，请刷新。");
      return required(
        await api.POST(
          decision.reject
            ? "/api/v1/approvals/{id}/reject"
            : "/api/v1/approvals/{id}/approve",
          { params: { path: { id: decision.approval.id } } },
        ),
      );
    },
    onSuccess: () => {
      setDecision(null);
      setCancel(false);
      setNotice("操作已提交，正在更新状态。");
      void qc.invalidateQueries();
    },
    onError: () => {
      void task.refetch();
      void related.refetch();
    },
  });
  const hidden =
      errorDenies(task.error) ||
      errorDenies(related.error) ||
      errorDenies(works.error),
    t = hidden ? undefined : task.data,
    r = hidden ? undefined : related.data,
    title =
      works.data?.find((w) => w.id === t?.work_item_id)?.title ??
      t?.capability ??
      "工作详情";
  const pending = r?.approvals.filter((a) => a.state === "PENDING") ?? [];
  const canCancel =
    t && ["WAITING_APPROVAL", "QUEUED"].includes(t.state) && gate.allowed;
  const download = () => {
    if (t)
      exportRecord(
        {
          title,
          task: t,
          events: r?.events,
          attempts: r?.attempts,
          artifacts: r?.artifacts,
          exported_at: new Date().toISOString(),
          notice: "任务记录导出；不包含产物文件内容。",
        },
        `magicworkshop-task-${id}.json`,
      );
  };
  return (
    <>
      <Link className="ws-back" to="/workbench/history">
        ← 返回我的工作
      </Link>
      <Title
        eyebrow="WORK IN PROGRESS"
        title={title}
        description={
          t
            ? `更新于 ${new Date(t.updated_at).toLocaleString("zh-CN")}`
            : "正在读取工作记录"
        }
      >
        {t && <TaskStatus state={t.state} />}
      </Title>
      <QueryState
        error={task.error ?? related.error ?? works.error}
        loading={task.isPending}
        retry={() => {
          void task.refetch();
          void related.refetch();
          void works.refetch();
        }}
      />
      {t && (
        <>
          <section className="ws-task-summary">
            <div>
              <h2>
                {t.state === "SUCCEEDED"
                  ? "这份工作已完成。"
                  : t.state === "WAITING_APPROVAL"
                    ? "下一步，需要你确认。"
                    : t.state === "NEEDS_RECONCILIATION"
                      ? "先核对，再继续。"
                      : t.state === "FAILED"
                        ? "这次执行没有完成。"
                        : t.state === "EXPIRED"
                          ? "授权或任务已经过期。"
                          : t.state === "CANCELED"
                            ? "这份工作已停止。"
                            : "工作正在推进。"}
              </h2>
              <p>
                {t.state === "NEEDS_RECONCILIATION"
                  ? "系统不会自动重排或切换写主控。请在管理后台核对执行事实，避免重复执行。"
                  : t.state === "FAILED"
                    ? "查看下方尝试与事件记录。这里不会自动重试或把失败标记为完成。"
                    : t.state === "WAITING_APPROVAL"
                      ? "在下方核对目标、参数与有效期，再决定是否继续。"
                      : "当前为本地模拟流程。真实模型、文件内容和生产执行尚未接入。"}
              </p>
            </div>
            <div className="ws-actions">
              <button
                onClick={() => {
                  void task.refetch();
                  void related.refetch();
                }}
              >
                <RefreshCw size={15} />
                刷新状态
              </button>
              <button disabled={!r || !!related.error} onClick={download}>
                <ArrowDownToLine size={15} />
                导出任务记录
              </button>
              {canCancel && (
                <button
                  onClick={() => {
                    mutation.reset();
                    setCancel(true);
                  }}
                >
                  取消这份工作
                </button>
              )}
            </div>
          </section>
          {notice && (
            <p className="ws-notice" role="status">
              {notice}
            </p>
          )}
          {pending.map((a) => {
            const expired = Date.parse(a.expires_at) <= Date.now(),
              canDecide =
                gate.allowed &&
                gate.boot.data?.features.approvals?.status === "MOCK_ONLY" &&
                a.risk === "MEDIUM" &&
                !expired;
            return (
              <section className="ws-approval" key={a.id}>
                <div className="ws-section-title">
                  <h2>
                    <ShieldCheck size={20} />
                    需要你的授权
                  </h2>
                  <span className="ws-tag">{a.risk}</span>
                </div>
                <p>
                  {expired
                    ? "此授权已过有效期，不能继续批准。"
                    : (a.scope ?? "请确认以下操作范围。")}
                </p>
                <dl>
                  <div>
                    <dt>操作</dt>
                    <dd>{a.action ?? t.capability}</dd>
                  </div>
                  <div>
                    <dt>目标</dt>
                    <dd>{a.resource_id ?? t.resource_id}</dd>
                  </div>
                  <div>
                    <dt>有效期至</dt>
                    <dd>{new Date(a.expires_at).toLocaleString("zh-CN")}</dd>
                  </div>
                </dl>
                <details>
                  <summary>查看脱敏参数</summary>
                  <KeyValues value={a.arguments_redacted ?? {}} />
                </details>
                <div className="ws-actions">
                  <button
                    className="ws-primary"
                    disabled={!canDecide}
                    onClick={() => {
                      mutation.reset();
                      setDecision({ approval: a, reject: false });
                    }}
                  >
                    允许这次操作 <Check size={15} />
                  </button>
                  <button
                    disabled={!canDecide}
                    onClick={() => {
                      mutation.reset();
                      setDecision({ approval: a, reject: true });
                    }}
                  >
                    拒绝
                  </button>
                  {!canDecide && (
                    <span>当前授权不可操作，请刷新确认状态。</span>
                  )}
                </div>
              </section>
            );
          })}
          <div className="ws-detail-grid">
            <section className="ws-panel">
              <h2>工作进展</h2>
              {r?.events.length ? (
                <ol className="ws-timeline">
                  {r.events
                    .sort((a, b) => a.sequence - b.sequence)
                    .map((e) => (
                      <li key={e.id}>
                        <span className="ws-timeline-dot" />
                        <div>
                          <strong>
                            {taskStates[e.kind as Schema<"Task">["state"]] ??
                              e.kind}
                          </strong>
                          <p>{e.summary}</p>
                          <DateLabel value={e.occurred_at} />
                        </div>
                      </li>
                    ))}
                </ol>
              ) : (
                <p>暂无事件记录。{related.isPending ? "正在读取…" : ""}</p>
              )}
            </section>
            <section className="ws-panel">
              <h2>结果与产物</h2>
              {r?.artifacts.length ? (
                r.artifacts.map((a) => <ArtifactCard key={a.id} artifact={a} />)
              ) : (
                <Empty
                  title={
                    t.state === "SUCCEEDED"
                      ? "任务已完成，未登记产物"
                      : "还没有可用产物"
                  }
                >
                  结果以服务端实际登记为准。失败、拒绝和失联不会生成成功结果。
                </Empty>
              )}
              <p className="ws-small-note">
                产物卡仅展示元数据，不会自动访问
                URI。可导出任务记录，不能据此下载真实产物文件。
              </p>
            </section>
          </div>
          <details className="ws-panel ws-trace">
            <summary>执行记录与追踪</summary>
            <dl>
              <div>
                <dt>任务编号</dt>
                <dd>{t.id}</dd>
              </div>
              <div>
                <dt>追踪编号</dt>
                <dd>{t.trace_id}</dd>
              </div>
              <div>
                <dt>风险 / 模式</dt>
                <dd>
                  {t.risk ?? "UNKNOWN"} / {t.dry_run ? "DRY RUN" : "未确认"}
                </dd>
              </div>
            </dl>
            <h3>执行尝试</h3>
            {r?.attempts.length ? (
              r.attempts.map((a) => <KeyValues key={a.id} value={a} />)
            ) : (
              <p>暂无执行尝试。</p>
            )}
            <h3>授权记录</h3>
            {r?.approvals.map((a) => (
              <p key={a.id}>
                {a.state} · {new Date(a.created_at).toLocaleString("zh-CN")}
              </p>
            ))}
            <Link to={`/tasks/${id}`}>
              在管理后台查看 <ArrowRight size={14} />
            </Link>
          </details>
          <ProvenanceTooltip meta={gate.boot.data?.source_meta} />
        </>
      )}
      {(decision || cancel) && (
        <ConfirmationDialog
          confirmLabel={
            cancel ? "确认取消" : decision?.reject ? "确认拒绝" : "确认允许"
          }
          confirmDisabled={!gate.allowed}
          title={
            cancel
              ? "取消这份工作？"
              : decision?.reject
                ? "拒绝这次操作？"
                : "允许这次操作？"
          }
          pending={mutation.isPending}
          onClose={() => {
            if (!mutation.isPending) {
              setDecision(null);
              setCancel(false);
            }
          }}
          onConfirm={() => mutation.mutate()}
        >
          <p>
            {cancel
              ? "只会向当前服务端提交取消请求，实际是否可取消以最新状态为准。"
              : decision?.reject
                ? "拒绝后不会继续执行这条模拟任务。"
                : "仅授权本次本地模拟操作，不授予持续权限。"}
          </p>
          {decision && (
            <>
              <p>目标：{decision.approval.resource_id}</p>
              <KeyValues value={decision.approval.arguments_redacted ?? {}} />
            </>
          )}
          {mutation.error && (
            <p role="alert" className="error-text">
              {mutation.error.message}
            </p>
          )}
        </ConfirmationDialog>
      )}
    </>
  );
}

export function WorkspaceNotFound() {
  return (
    <Empty title="没有找到这份工作">
      <Link to="/">返回工作坊</Link>
    </Empty>
  );
}
