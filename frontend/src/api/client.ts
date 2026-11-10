import { setConnected } from "../app/connection";
import createClient from "openapi-fetch";
import type { paths, components } from "./generated/schema";
import {
  apiConfig,
  assertLocalBase as localBase,
  type ApiMode,
} from "./config";
export type Schema<K extends keyof components["schemas"]> =
  components["schemas"][K];
export class ApiError extends Error {
  constructor(
    public status: number,
    public traceId?: string,
    public code?: string,
  ) {
    super(
      code === "session_read_only"
        ? "当前发布为只读模式，执行入口尚未开放"
        : code === "csrf_required"
          ? "会话校验已失效，请重新登录"
          : code === "upstream_contract_mismatch"
            ? "接口响应与锁定契约不一致，已暂停读取"
            : ((
                {
                  400: "请求参数不符合本地接口要求",
                  401: "身份已失效，请重新验证",
                  403: "没有查看或操作权限",
                  404: "未找到可见记录",
                  409: "状态冲突，请刷新后重试",
                  503: "新 API 暂不可用",
                } as Record<number, string>
              )[status] ?? "请求失败，请稍后重试"),
    );
  }
}
const config = apiConfig(
  {
    mode: import.meta.env.VITE_API_MODE,
    localOrigin: import.meta.env.VITE_LOCAL_API_ORIGIN,
    publicOrigin: import.meta.env.VITE_PUBLIC_ORIGIN,
    sessionWrites: import.meta.env.VITE_SESSION_WRITES,
  },
  location.origin,
);
export const API_MODE = (import.meta.env.VITE_API_MODE ?? "mock") as ApiMode,
  API_ORIGIN = config.origin,
  API_WRITES_ALLOWED = config.canWrite;
export function assertLocalBase(base: string) {
  return localBase(base, location.origin);
}
export async function establishWebSession() {
  // Verify the existing server-side cookie session. Never mint a local actor,
  // send a fixed bearer or register the mock service worker in session mode.
  const r = await fetch(`${API_ORIGIN}/api/v1/me`, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(10000),
  });
  if (!r.ok) throw new ApiError(r.status);
  const me: unknown = await r.json();
  if (
    !me ||
    typeof me !== "object" ||
    !("id" in me) ||
    typeof me.id !== "string" ||
    !me.id ||
    !("role" in me) ||
    typeof me.role !== "string" ||
    !("allowed_scopes" in me) ||
    !Array.isArray(me.allowed_scopes)
  )
    throw new ApiError(503);
}
let localCsrf = "";
export async function establishLocalSession() {
  const r = await fetch("/local/session", {
    method: "POST",
    credentials: "same-origin",
  });
  if (!r.ok) throw new ApiError(r.status);
  const body: unknown = await r.json();
  if (
    !body ||
    typeof body !== "object" ||
    !("csrf" in body) ||
    typeof body.csrf !== "string"
  )
    throw Error("Invalid local session");
  localCsrf = body.csrf;
}
export const api = createClient<paths>({
  baseUrl: API_ORIGIN,
  credentials: "same-origin",
  fetch: async (request) => {
    if (API_MODE === "session") {
      if (
        new URL(request.url).origin !== API_ORIGIN ||
        new URL(request.url).pathname.includes("/workers/")
      )
        throw new ApiError(403);
      if (request.method !== "GET") {
        if (!API_WRITES_ALLOWED)
          throw new ApiError(403, undefined, "session_read_only");
        let csrf: string | null = null;
        try {
          csrf = localStorage.getItem("mwcp_csrf");
        } catch {
          /* refuse if storage is unavailable */
        }
        if (!csrf || csrf.length > 256 || !/^[A-Za-z0-9_-]+$/.test(csrf))
          throw new ApiError(403, undefined, "csrf_required");
        request.headers.set("X-MW-CSRF", csrf);
      }
    }
    if (API_MODE === "loopback" && request.method !== "GET")
      request.headers.set("X-MW-CSRF", localCsrf);
    const controller = new AbortController();
    const abort = () => controller.abort();
    request.signal.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(abort, 10000);
    try {
      const response = await fetch(
        new Request(request, { signal: controller.signal }),
      );
      if (response.status >= 500 && !request.url.includes("/health/ready"))
        setConnected(false);
      else if (response.ok) setConnected(true);
      if (!response.ok) {
        let trace: string | undefined;
        let code: string | undefined;
        try {
          const body: unknown = await response.clone().json();
          if (
            body &&
            typeof body === "object" &&
            "trace_id" in body &&
            typeof body.trace_id === "string"
          )
            trace = body.trace_id;
          if (
            body &&
            typeof body === "object" &&
            "error" in body &&
            body.error &&
            typeof body.error === "object" &&
            "code" in body.error &&
            typeof body.error.code === "string"
          )
            code = body.error.code;
        } catch {
          /* no raw error leakage */
        }
        throw new ApiError(response.status, trace, code);
      }
      return response;
    } catch (error) {
      if (!(error instanceof ApiError)) setConnected(false);
      throw error;
    } finally {
      clearTimeout(timer);
      request.signal.removeEventListener("abort", abort);
    }
  },
});
export function required<T>(result: { data?: T }): T {
  if (result.data === undefined) throw new Error("响应缺失");
  return result.data;
}
// SSE authentication stays same-origin. No bearer query, separate from JSON history.
export function subscribeEvents(
  onEvent: (id: string) => void,
  onFallback: () => void,
) {
  const stream = new EventSource(`${API_ORIGIN}/api/v1/events`, {
    withCredentials: true,
  });
  stream.onmessage = (e) => onEvent(e.lastEventId);
  stream.addEventListener("audit", (e) =>
    onEvent((e as MessageEvent).lastEventId),
  );
  stream.onerror = () => {
    onFallback();
  };
  return () => stream.close();
}
