import { fanoutResponse } from "./fanout";
import { http, HttpResponse, delay } from "msw";
import operations from "../api/generated/operations.json";
import { v2Response } from "./v2";
import { ledger } from "./engine";
import {
  nodes,
  resources,
  agents,
  capabilities,
  integrations,
  bootstrap,
  catalog,
  meta,
  now,
  uuid,
  identity,
} from "./fixtures";
import type { Schema } from "../api/client";
export type Scenario =
  | "normal"
  | "empty"
  | "offline"
  | "stale"
  | "loading"
  | "401"
  | "403"
  | "404"
  | "409"
  | "503";
export const control: {
  scenario: Scenario;
  outcome: "SUCCEEDED" | "FAILED" | "NEEDS_RECONCILIATION";
} = { scenario: "normal", outcome: "SUCCEEDED" };
function page<T>(items: T[], url: URL) {
  const offset = Number(url.searchParams.get("cursor") ?? 0),
    limit = Number(url.searchParams.get("limit") ?? 20);
  return {
    items:
      control.scenario === "empty" ? [] : items.slice(offset, offset + limit),
    next_cursor: offset + limit < items.length ? String(offset + limit) : null,
  };
}
function err(status: number) {
  return HttpResponse.json(
    {
      error: { code: `local_${status}`, message: "Local simulation error" },
      trace_id: uuid(),
    },
    { status },
  );
}
export const handlers = operations.map((op) =>
  http[op.method as "get" | "post" | "put" | "patch" | "delete"](
    (typeof location === "undefined" ? "http://localhost" : location.origin) +
      op.path.replace(/\{([^}]+)\}/g, ":$1"),
    async ({ request, params }) => {
      await delay(control.scenario === "loading" ? 2500 : 80);
      if (control.scenario === "offline") return HttpResponse.error();
      if (/^\d+$/.test(control.scenario)) return err(Number(control.scenario));
      const url = new URL(request.url),
        key = op.path.slice(8),
        id = String(params.id ?? "");
      try {
        if (op.x_phase === "V3")
          return await fanoutResponse(op.method, op.path, request, params);
        if (op.x_phase === "V2")
          return await v2Response(op.method, op.path, request, params);
        if (key === "events")
          return new HttpResponse(
            `retry: 15000\nid: ${ledger.events.at(-1)?.id ?? "0"}\ndata: {"summary":"LOCAL MOCK"}\n\n`,
            { headers: { "Content-Type": "text/event-stream" } },
          );
        let result: unknown;
        if (op.method === "post") {
          if (key === "tasks")
            return HttpResponse.json(
              ledger.create(
                (await request.json()) as Schema<"TaskCreate">,
                request.headers.get("Idempotency-Key") ?? "",
              ),
              { status: 202 },
            );
          if (key === "work-items") {
            const b = (await request.json()) as Schema<"WorkItemCreate">;
            const item: Schema<"WorkItem"> = {
              id: uuid(),
              title: b.title,
              kind: b.kind,
              status: "open",
              source_system: "LOCAL MOCK",
              created_at: now(),
              created_by: identity.id,
            };
            ledger.workItems.push(item);
            return HttpResponse.json(item, { status: 201 });
          } else if (key.endsWith("/cancel")) {
            const task = ledger.transition(id, "CANCELED");
            return HttpResponse.json(task, { status: 202 });
          } else if (key.startsWith("approvals/")) {
            const reject = key.endsWith("/reject");
            result = { ...ledger.approve(id, reject) };
            if (!reject) {
              const a = result as Schema<"Approval">;
              const requested = ledger.tasks.find((t) => t.id === a.task_id)
                ?.arguments_redacted?.outcome;
              const outcome =
                requested === "FAILED" || requested === "NEEDS_RECONCILIATION"
                  ? requested
                  : "SUCCEEDED";
              void ledger.run(a.task_id, outcome).catch(() => {});
            }
          } else return err(403); // Browser actor cannot act as Worker.
        } else if (key === "ui/bootstrap") result = bootstrap();
        else if (key === "me") result = identity;
        else if (key === "health/ready")
          return HttpResponse.json(
            {
              error: {
                code: "dependency_not_ready",
                message: "Production dependencies not connected",
              },
              trace_id: uuid(),
              status: "not_ready",
              checked_at: now(),
              dependency_status: {
                database: "not_connected",
                probes: "not_configured",
                workers: "mock",
              },
            },
            { status: 503 },
          );
        else if (key === "health/live")
          result = { status: "ok", checked_at: now() };
        else if (key === "dashboard/summary")
          result = {
            nodes: {
              items: nodes.map((n) => ({
                ...n,
                stale: control.scenario === "stale",
              })),
            },
            task_counts: {
              active: ledger.tasks.filter(
                (t) =>
                  !["SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"].includes(
                    t.state,
                  ),
              ).length,
              external: null,
              needs_reconciliation: ledger.tasks.filter(
                (t) => t.state === "NEEDS_RECONCILIATION",
              ).length,
            },
            approval_counts: {
              pending: ledger.approvals.filter((a) => a.state === "PENDING")
                .length,
            },
            recent_events: ledger.audit.slice(0, 5),
            source_meta: meta(),
          };
        else if (key === "events/history")
          result = { ...page(ledger.audit, url), source_meta: meta() };
        else if (key === "tasks/{id}/events")
          result = page(
            ledger.events.filter((e) => e.task_id === id),
            url,
          );
        else if (key === "tasks/{id}/attempts")
          result = {
            ...page(
              ledger.attempts.filter((a) => a.task_id === id),
              url,
            ),
            source_meta: meta(),
          };
        else if (
          [
            "workflows",
            "network/links",
            "models",
            "projects",
            "compute/runs",
            "knowledge",
          ].includes(key)
        )
          result = {
            ...catalog(key),
            ...(control.scenario === "empty" ? { items: [] } : {}),
          };
        else {
          const entries: Record<string, unknown[]> = {
            nodes: nodes.map((n) => ({
              ...n,
              stale: control.scenario === "stale",
            })),
            resources,
            services: resources.filter((r) => r.kind === "service"),
            agents,
            capabilities,
            "work-items": ledger.workItems,
            tasks: ledger.tasks,
            approvals: ledger.approvals,
            artifacts: ledger.artifacts,
            integrations,
            audit: ledger.audit,
            observations: resources.map((r) => ({
              resource_id: r.id,
              status: "unknown",
              observed_at: now(),
              ttl_seconds: 60,
              source: "synthetic-only",
              stale: control.scenario === "stale",
            })),
          };
          const root = key.split("/")[0],
            items = entries[root];
          if (!items) return err(404);
          if (params.id) {
            result = items.find(
              (item) =>
                !!item &&
                typeof item === "object" &&
                "id" in item &&
                item.id === id,
            );
            if (!result) return err(404);
          } else {
            let filtered = items;
            if (root === "resources" && url.searchParams.has("kind"))
              filtered = resources.filter(
                (r) => r.kind === url.searchParams.get("kind"),
              );
            result = page(filtered, url);
          }
        }
        return new HttpResponse(JSON.stringify(result), {
          headers: { "Content-Type": "application/json" },
        });
      } catch (e) {
        return err(typeof e === "number" ? e : 409);
      }
    },
  ),
);
