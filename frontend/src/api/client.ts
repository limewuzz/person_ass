import { setConnected } from "../app/connection";
import createClient from "openapi-fetch";
import type { paths, components } from "./generated/schema";
export type Schema<K extends keyof components["schemas"]> =
  components["schemas"][K];
export class ApiError extends Error {
  constructor(
    public status: number,
    public traceId?: string,
    public code?: string,
  ) {
    super(
      code === "upstream_contract_mismatch"
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
export const API_MODE =
  import.meta.env.VITE_API_MODE === "loopback" ? "loopback" : "mock";
export const API_ORIGIN =
  import.meta.env.VITE_LOCAL_API_ORIGIN ?? location.origin;
export function assertLocalBase(base: string) {
  const u = new URL(base, location.origin);
  if (
    !["http:", "https:"].includes(u.protocol) ||
    u.username ||
    u.password ||
    ["3100", "8765", "8123"].includes(u.port) ||
    (u.hostname !== "127.0.0.1" && u.hostname !== "localhost")
  )
    throw new Error("Only new loopback API allowed");
  return u.origin;
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
  baseUrl: assertLocalBase(API_ORIGIN),
  credentials: "same-origin",
  fetch: async (request) => {
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
  const stream = new EventSource(
    `${assertLocalBase(API_ORIGIN)}/api/v1/events`,
    { withCredentials: true },
  );
  stream.onmessage = (e) => onEvent(e.lastEventId);
  stream.addEventListener("audit", (e) =>
    onEvent((e as MessageEvent).lastEventId),
  );
  stream.onerror = () => {
    onFallback();
  };
  return () => stream.close();
}
