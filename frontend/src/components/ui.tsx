import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Info,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { ApiError, type Schema } from "../api/client";
export function HealthBadge({ value }: { value?: string | null }) {
  const v = value ?? "UNKNOWN";
  return (
    <span className={`badge ${v.toLowerCase()}`}>
      {["healthy", "SUCCEEDED", "APPROVED"].includes(v) ? (
        <CheckCircle2 size={12} />
      ) : (
        <Info size={12} />
      )}{" "}
      {v.toUpperCase()}
    </span>
  );
}
export function ProvenanceTooltip({
  meta,
}: {
  meta?: Schema<"DataSourceMeta">;
}) {
  return (
    <details className="provenance">
      <summary>
        <Info size={12} /> {meta?.data_mode ?? "UNKNOWN"} ·{" "}
        {meta?.freshness ?? "UNKNOWN"} · 数据来源
      </summary>
      <dl>
        {Object.entries(
          meta ?? {
            source_system: "暂无可靠来源",
            observed_at: null,
            received_at: null,
            ttl_seconds: null,
          },
        ).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v === null ? "—" : String(v)}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
export function FeatureGate({
  allowed,
  reason,
  children,
}: {
  allowed: boolean;
  reason: string;
  children: ReactNode;
}) {
  return allowed ? (
    <>{children}</>
  ) : (
    <span className="muted" role="note">
      🔒 {reason}
    </span>
  );
}
export function StatePanel({
  kind,
  children,
  retry,
}: {
  kind: string;
  children?: ReactNode;
  retry?: () => void;
}) {
  return (
    <section
      className="state-panel"
      role={kind === "LOADING" ? "status" : "alert"}
    >
      <AlertTriangle size={26} />
      <h2>{kind}</h2>
      <p>{children}</p>
      {retry && (
        <button onClick={retry}>
          <RefreshCw size={14} /> 重试
        </button>
      )}
    </section>
  );
}
export function QueryState({
  error,
  loading,
  retry,
}: {
  error: Error | null;
  loading: boolean;
  retry: () => void;
}) {
  if (loading)
    return <StatePanel kind="LOADING">正在读取新平台数据…</StatePanel>;
  if (error)
    return (
      <StatePanel
        kind={error instanceof ApiError ? String(error.status) : "OFFLINE"}
        retry={retry}
      >
        {error instanceof ApiError
          ? error.message
          : "无法连接新 API。缓存只读；不会切换写主控。"}
      </StatePanel>
    );
  return null;
}
export function FilterToolbar({
  search,
  setSearch,
  status,
  setStatus,
  options,
  sort,
  setSort,
}: {
  search: string;
  setSearch: (s: string) => void;
  status: string;
  setStatus: (s: string) => void;
  options: string[];
  sort: boolean;
  setSort: (v: boolean) => void;
}) {
  return (
    <div className="filter-toolbar">
      <label className="search">
        <Search size={15} />
        <input
          aria-label="搜索记录"
          placeholder="搜索名称、状态、归属…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </label>
      <select
        aria-label="状态筛选"
        value={status}
        onChange={(e) => setStatus(e.target.value)}
      >
        <option value="">全部状态</option>
        {options.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
      <button aria-label="名称排序" onClick={() => setSort(!sort)}>
        名称 {sort ? "↓" : "↑"}
      </button>
    </div>
  );
}
export function CursorPagination({
  page,
  total,
  setPage,
}: {
  page: number;
  total: number;
  setPage: (p: number) => void;
}) {
  return (
    <div className="pagination">
      <span>
        {total} 条记录 · 第 {page + 1} 页
      </span>
      <button
        aria-label="上一页"
        disabled={page === 0}
        onClick={() => setPage(page - 1)}
      >
        <ChevronLeft size={14} />
      </button>
      <button
        aria-label="下一页"
        disabled={(page + 1) * 4 >= total}
        onClick={() => setPage(page + 1)}
      >
        <ChevronRight size={14} />
      </button>
    </div>
  );
}
export function EntityDetailTabs({
  tabs,
  tab,
  setTab,
}: {
  tabs: readonly string[];
  tab: string;
  setTab: (s: string) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  return (
    <div className="tabs" role="tablist" ref={root} aria-label="实体详情视图">
      {tabs.map((t, index) => (
        <button
          id={`detail-tab-${t}`}
          key={t}
          role="tab"
          tabIndex={t === tab ? 0 : -1}
          aria-controls="entity-detail-panel"
          aria-selected={t === tab}
          onClick={() => setTab(t)}
          onKeyDown={(e) => {
            let next = index;
            if (e.key === "ArrowRight") next = (index + 1) % tabs.length;
            else if (e.key === "ArrowLeft")
              next = (index + tabs.length - 1) % tabs.length;
            else if (e.key === "Home") next = 0;
            else if (e.key === "End") next = tabs.length - 1;
            else return;
            e.preventDefault();
            setTab(tabs[next]);
            root.current?.querySelectorAll("button")[next]?.focus();
          }}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
export function TaskTimeline({ events }: { events: Schema<"TaskEvent">[] }) {
  return (
    <ol className="timeline">
      {events.map((e) => (
        <li key={e.id}>
          <span className="timeline-dot" />
          <div>
            <strong>{e.kind}</strong>
            <p>{e.summary}</p>
            <time>{new Date(e.occurred_at).toLocaleString()}</time>
          </div>
        </li>
      ))}
      {!events.length && <li>暂无事件</li>}
    </ol>
  );
}
export function ConfirmationDialog({
  title,
  children,
  onConfirm,
  onClose,
  pending = false,
}: {
  title: string;
  children: ReactNode;
  onConfirm: () => void;
  onClose: () => void;
  pending?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    d?.showModal();
    return () => d?.close();
  }, []);
  return (
    <dialog
      aria-label={title}
      ref={ref}
      onCancel={onClose}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="dialog-head">
        <h2>{title}</h2>
        <button onClick={onClose} aria-label="关闭">
          <X size={18} />
        </button>
      </div>
      {children}
      <div className="dialog-actions">
        <button onClick={onClose}>返回</button>
        <button className="primary" disabled={pending} onClick={onConfirm}>
          {pending ? "提交中…" : "确认 · LOCAL MOCK"}
        </button>
      </div>
    </dialog>
  );
}
export function KeyValues({ value }: { value: object }) {
  return (
    <dl className="key-values">
      {Object.entries(value).map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>
            {v === null || v === undefined
              ? "—"
              : typeof v === "object"
                ? JSON.stringify(v)
                : String(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function RiskApprovalPanel({
  approval,
  task,
  onDecide,
}: {
  approval: Schema<"Approval">;
  task?: Schema<"Task">;
  onDecide?: (reject: boolean) => void;
}) {
  const expired = Date.parse(approval.expires_at) < Date.now();
  return (
    <article className="panel approval-card">
      <div className="section-head">
        <strong>本地模拟审批</strong>
        <HealthBadge value={approval.risk} />
      </div>
      <KeyValues
        value={{
          requester: approval.requester_ref ?? "UNKNOWN",
          scope: approval.scope ?? "UNKNOWN",
          action: approval.action ?? task?.capability ?? "UNKNOWN",
          target: approval.resource_id ?? task?.resource_id ?? "UNKNOWN",
          arguments_summary:
            approval.arguments_redacted ??
            task?.arguments_redacted ??
            "UNKNOWN · 源未提供参数摘要",
          target_generation: approval.target_generation ?? "UNKNOWN",
          expires_at: approval.expires_at,
          state: approval.state,
        }}
      />
      <Link to={`/tasks/${approval.task_id}`}>查看关联任务 ↗</Link>
      {onDecide && approval.state === "PENDING" && (
        <div className="row">
          <button
            disabled={expired}
            className="primary"
            onClick={() => onDecide(false)}
          >
            演示批准
          </button>
          <button disabled={expired} onClick={() => onDecide(true)}>
            演示拒绝
          </button>
          {expired && <HealthBadge value="EXPIRED" />}
        </div>
      )}
    </article>
  );
}
