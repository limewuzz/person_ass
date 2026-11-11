import { HttpResponse } from "msw";
import type { Schema } from "../api/client";
import { identity, now, uuid } from "./fixtures";
import recipes from "./fanout-recipes.json";
import { sha256Hex } from "../workspace/model";
import { ledger } from "./engine";
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(stableJson).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, item]) => JSON.stringify(key) + ":" + stableJson(item))
        .join(",") +
      "}"
    );
  return JSON.stringify(value) ?? "null";
}
const plans = new Map<string, Schema<"FanoutPlan">>(),
  keys = new Map<string, { hash: string; id: string }>();
let revision = 0;
const error = (status: number, code: string) =>
  HttpResponse.json(
    { error: { code, message: "Local fanout simulation" }, trace_id: uuid() },
    { status },
  );
function update(p: Schema<"FanoutPlan">) {
  const states = new Set(p.deliveries.map((d) => d.state));
  p.status = states.has("WAITING_APPROVAL")
    ? "WAITING_APPROVAL"
    : states.has("NEEDS_RECONCILIATION")
      ? "NEEDS_RECONCILIATION"
      : states.size === 1 && states.has("SUCCEEDED")
        ? "SUCCEEDED"
        : states.has("SUCCEEDED")
          ? "PARTIAL"
          : states.has("QUEUED")
            ? "QUEUED"
            : "FAILED";
  p.revision = ++revision;
}
export async function fanoutResponse(
  method: string,
  path: string,
  request: Request,
  params: Record<string, unknown>,
) {
  if (path.includes("/workers/") || path.includes("/webhooks/"))
    return error(403, "browser_worker_forbidden");
  const text = method === "post" ? await request.text() : "",
    b = text ? JSON.parse(text) : {};
  if (path === "/api/v1/recipes")
    return HttpResponse.json({
      items: Object.entries(recipes).map(([id, r]) => ({
        id,
        name: r.name,
        version: 1,
        steps: r.steps.map(([step, target, risk, depends_on]) => ({
          id: step,
          target,
          risk,
          depends_on,
        })),
      })),
    });
  if (path === "/api/v1/fanouts") {
    if (method === "get")
      return HttpResponse.json({
        items: [...plans.values()],
        revision,
        next_cursor: null,
      });
    const key = request.headers.get("Idempotency-Key");
    if (!key || key.length < 12) return error(400, "idempotency_key_required");
    const recipe = recipes[b.recipe_id as keyof typeof recipes];
    if (!recipe) return error(400, "unknown_recipe");
    const hash = await sha256Hex(
        new TextEncoder().encode(
          stableJson({ body: b, work_item_id: params.work_item_id ?? null }),
        ),
      ),
      prior = keys.get(key);
    if (prior)
      return prior.hash === hash
        ? HttpResponse.json(plans.get(prior.id), { status: 201 })
        : error(409, "idempotency_conflict");
    if (
      !Array.isArray(b.targets) ||
      !b.targets.length ||
      b.targets.some(
        (id: string) => !recipe.steps.some(([step]) => step === id),
      )
    )
      return error(400, "invalid_targets");
    const selected = new Set<string>(b.targets);
    for (let i = 0; i < recipe.steps.length; i++)
      for (const [id, , , deps] of recipe.steps)
        if (selected.has(id as string))
          for (const dep of deps) selected.add(dep);
    const pid = uuid(),
      wi = String(params.work_item_id ?? uuid()),
      root = uuid();
    if (!params.work_item_id)
      ledger.workItems.push({
        id: wi,
        title: b.title,
        kind: b.recipe_id === "paper" ? "paper" : "task",
        status: "open",
        created_at: now(),
        created_by: identity.id,
      });
    const deliveries: Schema<"FanoutDelivery">[] = recipe.steps
      .filter(([id]) => selected.has(id as string))
      .map(([step, target, risk, deps]) => ({
        id: uuid(),
        plan_id: pid,
        task_id: uuid(),
        step_id: step as string,
        target: target as string,
        risk: risk as "LOW" | "MEDIUM",
        depends_on: deps as string[],
        state: risk === "MEDIUM" ? "WAITING_APPROVAL" : "QUEUED",
        attempts: 0,
        generation: 0,
        next_retry_at: 0,
        lease_expires_at: 0,
        worker_id: null,
        receipt: null,
        last_error: null,
      }));
    const needs = deliveries.some((d) => d.risk === "MEDIUM"),
      aid = needs ? uuid() : null;
    const p: Schema<"FanoutPlan"> = {
      id: pid,
      work_item_id: wi,
      task_id: root,
      trace_id: uuid(),
      owner_sub: identity.id,
      title: b.title,
      input: b.input,
      recipe_id: b.recipe_id,
      recipe_version: 1,
      mode: b.mode,
      origin: b.origin,
      parameters: b.parameters ?? {},
      plan_hash: hash,
      approval_id: aid,
      approval: aid
        ? {
            id: aid,
            task_id: root,
            state: "PENDING",
            risk: "MEDIUM",
            expires_at: new Date(Date.now() + 600000).toISOString(),
            created_at: now(),
          }
        : null,
      revision: 0,
      created_at: now(),
      delivery_ids: deliveries.map((d) => d.id),
      deliveries,
      status: "QUEUED",
      availability: b.mode === "SIMULATE" ? "MOCK" : "UNAVAILABLE",
    };
    update(p);
    plans.set(pid, p);
    keys.set(key, { hash, id: pid });
    return HttpResponse.json(p, { status: 201 });
  }
  const p = plans.get(String(params.id));
  if (!p) return error(404, "not_found");
  if (path.endsWith("/stream"))
    return new HttpResponse(
      `id: ${p.id}:${p.revision}\nevent: fanout\ndata: ${JSON.stringify(p)}\n\n`,
      { headers: { "Content-Type": "text/event-stream" } },
    );
  if (path.endsWith("/decision")) {
    if (p.approval?.state !== "PENDING") return error(409, "approval_state");
    p.approval.state = b.decision === "approved" ? "CONSUMED" : "REJECTED";
    for (const d of p.deliveries)
      if (d.state === "WAITING_APPROVAL")
        d.state = b.decision === "approved" ? "QUEUED" : "CANCELED";
    update(p);
  }
  if (path.endsWith("/simulate")) {
    if (p.mode !== "SIMULATE") return error(403, "simulation_only");
    // Snapshot eligibility, as the backend claim batch does; dependencies advance next round.
    const ready = p.deliveries.filter(
      (d) =>
        d.state === "QUEUED" &&
        d.next_retry_at <= Date.now() / 1000 &&
        (!b.target || d.target === b.target) &&
        d.depends_on.every(
          (s) =>
            p.deliveries.find((x) => x.step_id === s)?.state === "SUCCEEDED",
        ),
    );
    for (const d of ready) {
      d.attempts++;
      d.generation++;
      if (b.outcome === "RETRYABLE") {
        d.state = d.attempts >= 5 ? "NEEDS_RECONCILIATION" : "QUEUED";
        d.next_retry_at = Date.now() / 1000 + 2 ** d.attempts;
        d.last_error = "simulated_transient_failure";
      } else if (b.outcome === "UNKNOWN") {
        d.state = "NEEDS_RECONCILIATION";
      } else {
        d.state = "SUCCEEDED";
        const bytes = new TextEncoder().encode(
          JSON.stringify({
            simulation: true,
            delivery_id: d.id,
            target: d.target,
          }),
        );
        d.receipt = {
          uri: `mock://fanout/${d.id}`,
          sha256: await sha256Hex(bytes),
          source_mode: "MOCK",
          byte_size: bytes.length,
        };
      }
    }
    update(p);
  }
  if (path.endsWith("/reconcile")) {
    const d = p.deliveries.find((d) => d.id === params.delivery_id);
    if (
      !d ||
      d.state !== "NEEDS_RECONCILIATION" ||
      d.generation !== b.expected_generation
    )
      return error(409, "reconciliation_conflict");
    if (
      typeof b.reason !== "string" ||
      b.reason.length < 10 ||
      b.reason.length > 500
    )
      return error(400, "reconciliation_reason_required");
    if (
      b.resolution === "ACCEPT_RECEIPT" &&
      (!b.receipt ||
        !/^[a-f0-9]{64}$/.test(b.receipt.sha256) ||
        !/^(mock|https|file|reminders|x-apple-reminderkit):\/\//.test(
          b.receipt.uri,
        ) ||
        b.receipt.source_mode !== (p.mode === "SIMULATE" ? "MOCK" : "LIVE"))
    )
      return error(400, "invalid_reconciliation_receipt");
    d.state =
      b.resolution === "RETRY_CONFIRMED_NOT_EXECUTED"
        ? "QUEUED"
        : b.resolution === "ACCEPT_RECEIPT"
          ? "SUCCEEDED"
          : "FAILED";
    d.next_retry_at = 0;
    if (b.receipt) d.receipt = b.receipt;
    update(p);
  }
  return HttpResponse.json(p);
}
