import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight,
  Check,
  GitBranch,
  RefreshCw,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import {
  api,
  required,
  API_MODE,
  API_ORIGIN,
  API_WRITES_ALLOWED,
  ApiError,
  type Schema,
} from "../api/client";
import { useConnection } from "../app/connection";
import "./fanout.css";
import { isRecipe, portalDraftKey, readPortalDraft } from "./portal-handoff";
const labels: Record<string, string> = {
  ai: "AI 摘要",
  drive: "Google Drive",
  notion: "Notion",
  reminders: "Mac · 提醒事项",
  github: "GitHub",
  compute: "Colab / Mac 算力",
  implementation: "开发任务",
  wechat: "微信通知",
  knowledge: "上下文检索",
};
const states: Record<string, string> = {
  QUEUED: "等待调度",
  WAITING_APPROVAL: "等待授权",
  RUNNING: "执行中",
  SUCCEEDED: "已完成",
  PARTIAL: "部分完成",
  FAILED: "已失败",
  CANCELED: "已取消",
  EXPIRED: "已过期",
  NEEDS_RECONCILIATION: "需要对账",
};
const denied = (e: unknown) =>
  e instanceof ApiError && [401, 403, 404].includes(e.status);
const pendingKey = "mw.v3.fanout.pending";
function readPending(): { body: Schema<"FanoutCreate">; key: string } | null {
  try {
    const x = JSON.parse(sessionStorage.getItem(pendingKey) ?? "null");
    return x &&
      typeof x.key === "string" &&
      x.body &&
      typeof x.body.title === "string"
      ? x
      : null;
  } catch {
    return null;
  }
}
export function FanoutWorkspace() {
  const nav = useNavigate(),
    { id } = useParams(),
    qc = useQueryClient(),
    connected = useConnection();
  const [tab, setTab] = useState("流水线"),
    [recipe, setRecipe] = useState("paper"),
    [targets, setTargets] = useState<string[]>([
      "archive",
      "paper",
      "reminder",
    ]),
    [title, setTitle] = useState("新的跨平台工作"),
    [input, setInput] = useState(""),
    [mode, setMode] = useState<"SIMULATE" | "LIVE">("SIMULATE"),
    [origin, setOrigin] = useState<Schema<"FanoutOrigin">["channel"]>("web"),
    [pending, setPending] = useState(readPending),
    [failureTarget, setFailureTarget] = useState("notion"),
    [reason, setReason] = useState(""),
    [receiptUri, setReceiptUri] = useState(""),
    [receiptSha, setReceiptSha] = useState("");
  const inFlight = useRef(false);
  const portalApplied = useRef(false);
  const recipes = useQuery({
    queryKey: ["fanout", "recipes"],
    queryFn: async () => required(await api.GET("/api/v1/recipes")),
  });
  const history = useQuery({
    queryKey: ["fanout", "history"],
    queryFn: async () => required(await api.GET("/api/v1/fanouts")),
    refetchInterval: 2000,
  });
  const detail = useQuery({
    queryKey: ["fanout", "plan", id],
    enabled: !!id,
    queryFn: async () =>
      required(
        await api.GET("/api/v1/fanouts/{id}", {
          params: { path: { id: id! } },
        }),
      ),
    refetchInterval: 2000,
  });
  const me = useQuery({
    queryKey: ["fanout", "identity"],
    queryFn: async () => required(await api.GET("/api/v1/me")),
  });
  const hidden = [history.error, detail.error, me.error].some(denied),
    plan = hidden ? undefined : detail.data;
  const writable = connected && API_WRITES_ALLOWED && !hidden && !me.error;
  const canDecide =
    writable &&
    (API_MODE === "mock" ||
      !!me.data?.allowed_scopes.includes("approvals:decide"));
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["fanout"] });
  };
  useEffect(() => {
    if (!id || API_MODE === "mock") return;
    const stream = new EventSource(
      `${API_ORIGIN}/api/v1/fanouts/${id}/stream`,
      { withCredentials: true },
    );
    stream.addEventListener("fanout", (e) => {
      try {
        const next = JSON.parse(
          (e as MessageEvent).data,
        ) as Schema<"FanoutPlan">;
        qc.setQueryData<Schema<"FanoutPlan">>(["fanout", "plan", id], (old) =>
          !old || next.revision > old.revision ? next : old,
        );
      } catch {
        /* polling remains available */
      }
    });
    stream.addEventListener("authorization_lost", () => {
      qc.removeQueries({ queryKey: ["fanout", "plan", id] });
      void qc.invalidateQueries({ queryKey: ["fanout"] });
      stream.close();
    });
    return () => stream.close();
  }, [id, qc]);
  const create = useMutation({
    mutationFn: async () => {
      if (!writable || inFlight.current)
        throw Error("当前不能提交，请检查连接与身份。");
      inFlight.current = true;
      try {
        const journal = pending ?? {
          key: crypto.randomUUID(),
          body: {
            recipe_id: recipe as Schema<"FanoutCreate">["recipe_id"],
            title,
            input,
            mode,
            targets,
            origin: { channel: origin },
          },
        };
        sessionStorage.setItem(pendingKey, JSON.stringify(journal));
        setPending(journal);
        return required(
          await api.POST("/api/v1/fanouts", {
            params: { header: { "Idempotency-Key": journal.key } },
            body: journal.body,
          }),
        );
      } finally {
        inFlight.current = false;
      }
    },
    onSuccess: (p) => {
      sessionStorage.removeItem(pendingKey);
      sessionStorage.removeItem(portalDraftKey);
      setPending(null);
      nav(`/workbench/fanout/${p.id}`);
      refresh();
    },
  });
  const decision = useMutation({
    mutationFn: async (d: "approved" | "rejected") =>
      required(
        await api.POST("/api/v1/fanouts/{id}/decision", {
          params: { path: { id: id! } },
          body: { decision: d },
        }),
      ),
    onSuccess: refresh,
  });
  const simulate = useMutation({
    mutationFn: async (fail: boolean) =>
      required(
        await api.POST("/api/v1/fanouts/{id}/simulate", {
          params: { path: { id: id! } },
          body: fail
            ? { target: failureTarget, outcome: "RETRYABLE" }
            : { outcome: "SUCCEEDED" },
        }),
      ),
    onSuccess: refresh,
  });
  const reconcile = useMutation({
    mutationFn: async (d: {
      delivery: Schema<"FanoutDelivery">;
      resolution: Schema<"FanoutReconcile">["resolution"];
    }) =>
      required(
        await api.POST(
          "/api/v1/fanouts/{id}/deliveries/{delivery_id}/reconcile",
          {
            params: { path: { id: id!, delivery_id: d.delivery.id } },
            body: {
              expected_generation: d.delivery.generation,
              resolution: d.resolution,
              reason,
              ...(d.resolution === "ACCEPT_RECEIPT"
                ? {
                    receipt: {
                      uri: receiptUri,
                      sha256: receiptSha,
                      source_mode: plan?.mode === "SIMULATE" ? "MOCK" : "LIVE",
                    },
                  }
                : {}),
            },
          },
        ),
      ),
    onSuccess: refresh,
  });
  const error =
    recipes.error ??
    history.error ??
    detail.error ??
    me.error ??
    create.error ??
    decision.error ??
    simulate.error ??
    reconcile.error;
  useEffect(() => {
    if (!recipes.data || pending || id || portalApplied.current) return;
    let draft: ReturnType<typeof readPortalDraft> = null;
    try {
      draft = readPortalDraft(window.sessionStorage);
    } catch {
      /* Manual composition still works with storage disabled. */
    }
    const requested =
      draft?.recipe ?? new URLSearchParams(location.search).get("recipe");
    if (!isRecipe(requested)) {
      portalApplied.current = true;
      return;
    }
    const selected = recipes.data.items.find((r) => r.id === requested);
    if (!selected) {
      portalApplied.current = true;
      return;
    }
    setRecipe(requested);
    setTargets(selected.steps.filter((s) => s.risk === "LOW").map((s) => s.id));
    if (draft) {
      setInput(draft.input);
      setTitle(draft.input.split("\n")[0].slice(0, 120));
    }
    portalApplied.current = true;
  }, [recipes.data, pending, id]);
  const selectedRecipe = recipes.data?.items.find((r) => r.id === recipe);
  return (
    <>
      <div className="ws-page-title">
        <div>
          <span className="ws-eyebrow">SINGLE INPUT · MANY POSSIBILITIES</span>
          <h1>一次交办，多处协同。</h1>
          <p>把一个意图交给工作坊，看见每条分支的去向与结果。</p>
        </div>
        <button onClick={refresh}>
          <RefreshCw size={16} />
          刷新
        </button>
      </div>
      <div className="ws-notice">
        <ShieldCheck size={20} />
        <span>
          默认在新本地控制平面模拟。LIVE 还需连接器授权；Cherry Studio
          仅可手动粘贴总结，既有 8765 网关保持冻结。
        </span>
        <strong>
          {plan?.availability ?? (mode === "SIMULATE" ? "MOCK" : "UNAVAILABLE")}
        </strong>
      </div>
      <div className="fo-recipes" aria-label="触发配方">
        {recipes.data?.items.map((r) => (
          <button
            key={r.id}
            className={r.id === recipe ? "selected" : ""}
            disabled={!!pending}
            aria-pressed={r.id === recipe}
            onClick={() => {
              setRecipe(r.id);
              setTargets(
                r.steps.filter((s) => s.risk === "LOW").map((s) => s.id),
              );
              setTitle(r.name);
            }}
          >
            <Workflow size={22} />
            <strong>{r.name}</strong>
            <small>
              {r.steps.length} 条分支 · v{r.version}
            </small>
          </button>
        ))}
      </div>
      <section className="ws-panel fo-composer" aria-label="统一工作项立项">
        <div className="fo-form">
          <label>
            工作标题
            <input
              value={title}
              disabled={!!pending}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label>
            这次想完成什么
            <textarea
              aria-label="多平台工作意图"
              maxLength={4000}
              value={input}
              disabled={!!pending}
              onChange={(e) => setInput(e.target.value)}
              placeholder="粘贴论文笔记、方案总结或交办内容…"
            />
          </label>
        </div>
        <div>
          <h2>选择协同分支</h2>
          <div className="fo-targets">
            {selectedRecipe?.steps.map((s) => (
              <label key={s.id}>
                <input
                  type="checkbox"
                  disabled={!!pending}
                  checked={targets.includes(s.id)}
                  onChange={(e) =>
                    setTargets((xs) =>
                      e.target.checked
                        ? [...xs, s.id]
                        : xs.filter((x) => x !== s.id),
                    )
                  }
                />
                {labels[s.target] ?? s.target}
                <small>
                  {s.risk === "MEDIUM" ? "需合并审批" : "预授权后可自动处理"}
                </small>
              </label>
            ))}
          </div>
        </div>
        <div className="ws-actions">
          <label>
            入口
            <select
              value={origin}
              disabled={!!pending}
              onChange={(e) => setOrigin(e.target.value as typeof origin)}
            >
              {[
                "web",
                "rakazo",
                "wechat",
                "manual",
                "colab",
                "android",
                "macos",
                "windows",
                "shortcuts",
              ].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            执行方式
            <select
              aria-label="执行方式"
              value={mode}
              disabled={!!pending}
              onChange={(e) => setMode(e.target.value as typeof mode)}
            >
              <option value="SIMULATE">本地模拟</option>
              <option value="LIVE">LIVE · 需要连接器授权</option>
            </select>
          </label>
          <button
            className="ws-primary"
            disabled={
              !writable ||
              create.isPending ||
              (!pending && (!input.trim() || !title.trim() || !targets.length))
            }
            onClick={() => create.mutate()}
          >
            {pending ? "继续原提交" : "一键发起协同流水线"}
            <ArrowRight size={16} />
          </button>
          {pending && (
            <button
              onClick={() => {
                if (confirm("请先核对流水线列表，确认没有未知提交后再清除。")) {
                  sessionStorage.removeItem(pendingKey);
                  setPending(null);
                }
              }}
            >
              核对后清除提交记录
            </button>
          )}
        </div>
        <small>
          只立项一次；重复提交沿用同一幂等键。依赖步骤会自动纳入，已成功的分支不会因其他分支失败而重跑。
        </small>
      </section>
      {error && (
        <div className="ws-notice" role="alert">
          {error instanceof Error ? error.message : "接口不可用"}
        </div>
      )}
      <div className="fo-tabs" role="group" aria-label="流水线视图">
        {["流水线", "Outbox 队列", "快捷指令"].map((t) => (
          <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      {tab === "快捷指令" ? (
        <section className="ws-panel">
          <h2>从外部入口发起</h2>
          <p>
            微信、Rakazo 或 Mac
            快捷指令统一发到控制平面。签名密钥保存在调用端私有文件中，不粘贴到浏览器。
          </p>
          <pre className="fo-command">
            python scripts/mw_trigger.py --url https://YOUR-CONTROL-PLANE
            --request-file intent.json --key-id YOUR-KEY-ID --key-file
            /run/secrets/trigger-key --idempotency-key YOUR-STABLE-INTENT-ID
            --allow-remote
          </pre>
          <p>
            HMAC 绑定原始正文、时间、随机 nonce 和幂等键。端点：POST
            /api/v1/webhooks/trigger。签名配置和真实连接器默认未启用。
          </p>
        </section>
      ) : (
        <>
          <section className="fo-history" aria-label="协同流水线列表">
            {!hidden &&
              history.data?.items.map((p) => (
                <button
                  key={p.id}
                  aria-pressed={p.id === id}
                  onClick={() => nav(`/workbench/fanout/${p.id}`)}
                >
                  <GitBranch size={16} />
                  {p.title}
                  <small>{states[p.status] ?? p.status}</small>
                </button>
              ))}
          </section>
          {plan ? (
            <section className="ws-panel" aria-label="协同流水线详情">
              <div className="ws-section-title">
                <div>
                  <h2>{plan.title}</h2>
                  <small>
                    一次立项 · {plan.deliveries.length} 条分支 · 修订{" "}
                    {plan.revision}
                  </small>
                </div>
                <strong>
                  {states[plan.status] ?? plan.status} · {plan.availability}
                </strong>
              </div>
              {plan.approval?.state === "PENDING" && (
                <div className="ws-notice">
                  <ShieldCheck />
                  <span>
                    一张审批单涵盖本次全部中风险分支。低风险分支独立推进。
                  </span>
                  <button
                    className="ws-primary"
                    disabled={!canDecide || decision.isPending}
                    onClick={() => decision.mutate("approved")}
                  >
                    允许这次操作
                  </button>
                  <button
                    disabled={!canDecide || decision.isPending}
                    onClick={() => decision.mutate("rejected")}
                  >
                    拒绝中风险分支
                  </button>
                </div>
              )}
              {plan.availability === "UNAVAILABLE" && (
                <p role="status">
                  真实连接器尚未配置或授权，任务不会自动接触外部平台。
                </p>
              )}
              <div className="fo-branches">
                {plan.deliveries.map((d) => (
                  <article
                    key={d.id}
                    className="fo-branch"
                    data-state={d.state}
                  >
                    <div className="fo-branch-icon">
                      {d.state === "SUCCEEDED" ? <Check /> : <GitBranch />}
                    </div>
                    <div>
                      <h3>{labels[d.target] ?? d.target}</h3>
                      <p>{states[d.state] ?? d.state}</p>
                      <small>
                        {d.depends_on.length
                          ? `前置步骤：${d.depends_on.join("、")}`
                          : "可独立推进"}
                      </small>
                      {tab === "Outbox 队列" && (
                        <p>
                          尝试 {d.attempts} · 代数 {d.generation} ·{" "}
                          {d.next_retry_at > Date.now() / 1000
                            ? `退避至 ${new Date(d.next_retry_at * 1000).toLocaleTimeString()}`
                            : "无待生效退避"}
                        </p>
                      )}
                      {d.receipt && (
                        <div className="fo-receipt">
                          <strong>{d.receipt.source_mode} 产物回执</strong>
                          <code>{d.receipt.uri}</code>
                          <small>SHA-256：{d.receipt.sha256}</small>
                        </div>
                      )}
                      {d.last_error && <small>{d.last_error}</small>}
                      {d.state === "NEEDS_RECONCILIATION" && (
                        <div className="ws-actions">
                          <button
                            disabled={
                              !canDecide ||
                              reason.length < 10 ||
                              reconcile.isPending
                            }
                            onClick={() =>
                              reconcile.mutate({
                                delivery: d,
                                resolution: "RETRY_CONFIRMED_NOT_EXECUTED",
                              })
                            }
                          >
                            确认未执行后重试
                          </button>
                          <button
                            disabled={
                              !canDecide ||
                              reason.length < 10 ||
                              reconcile.isPending
                            }
                            onClick={() =>
                              reconcile.mutate({
                                delivery: d,
                                resolution: "FAIL",
                              })
                            }
                          >
                            确认失败并关闭
                          </button>
                          <button
                            disabled={
                              !canDecide ||
                              reason.length < 10 ||
                              !receiptUri ||
                              !/^[0-9a-f]{64}$/.test(receiptSha) ||
                              reconcile.isPending
                            }
                            onClick={() =>
                              reconcile.mutate({
                                delivery: d,
                                resolution: "ACCEPT_RECEIPT",
                              })
                            }
                          >
                            核验回执后完成
                          </button>
                        </div>
                      )}
                    </div>
                  </article>
                ))}
              </div>
              {plan.mode === "SIMULATE" && (
                <div className="ws-actions">
                  <button
                    className="ws-primary"
                    disabled={!writable || simulate.isPending}
                    onClick={() => simulate.mutate(false)}
                  >
                    推进本地模拟
                  </button>
                  <label>
                    故障分支
                    <select
                      value={failureTarget}
                      onChange={(e) => setFailureTarget(e.target.value)}
                    >
                      {Object.entries(labels).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    disabled={!writable || simulate.isPending}
                    onClick={() => simulate.mutate(true)}
                  >
                    模拟可重试失败
                  </button>
                </div>
              )}
              {plan.deliveries.some(
                (d) => d.state === "NEEDS_RECONCILIATION",
              ) && (
                <fieldset className="fo-reconcile">
                  <legend>先核实外部结果，再对账</legend>
                  <label>
                    对账依据（至少 10 字）
                    <input
                      value={reason}
                      maxLength={500}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </label>
                  <label>
                    已核验的产物 URI
                    <input
                      value={receiptUri}
                      onChange={(e) => setReceiptUri(e.target.value)}
                    />
                  </label>
                  <label>
                    已核验的 SHA-256
                    <input
                      value={receiptSha}
                      onChange={(e) => setReceiptSha(e.target.value)}
                    />
                  </label>
                  <small>
                    未知结果不自动重试。重试仅作用于这一分支，成功分支保持关闭。
                  </small>
                </fieldset>
              )}
            </section>
          ) : (
            <section className="ws-panel">
              <h2>从一个意图开始</h2>
              <p>
                选择一套配方，工作坊会将工作项、审批和各个平台的结果放在同一条轨迹里。
              </p>
            </section>
          )}
        </>
      )}
    </>
  );
}
