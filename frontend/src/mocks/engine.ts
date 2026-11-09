import type { Schema } from "../api/client";
import { now, uuid, identity } from "./fixtures";
export class Ledger {
  tasks: Schema<"Task">[] = [];
  approvals: Schema<"Approval">[] = [];
  events: Schema<"TaskEvent">[] = [];
  attempts: Schema<"TaskAttemptSummary">[] = [];
  artifacts: Schema<"Artifact">[] = [];
  audit: Schema<"AuditEvent">[] = [];
  workItems: Schema<"WorkItem">[] = [];
  private keys = new Map<
    string,
    { hash: string; accepted: Schema<"TaskAccepted"> }
  >();
  create(body: Schema<"TaskCreate">, key: string): Schema<"TaskAccepted"> {
    if (!key) throw 409;
    if (
      body.capability !== "local.simulate" ||
      body.resource_id !== "local-ledger"
    )
      throw 403;
    const hash = JSON.stringify(body),
      old = this.keys.get(key);
    if (old) {
      if (old.hash !== hash) throw 409;
      return { ...old.accepted, replayed: true };
    }
    const task: Schema<"Task"> = {
      id: uuid(),
      work_item_id: body.work_item_id,
      resource_id: body.resource_id,
      capability: body.capability,
      state: "WAITING_APPROVAL",
      risk: "MEDIUM",
      dry_run: true,
      arguments_redacted: body.arguments,
      origin: body.origin,
      generation: 0,
      created_at: now(),
      updated_at: now(),
      trace_id: uuid(),
    };
    this.tasks.unshift(task);
    this.approvals.unshift({
      id: uuid(),
      task_id: task.id,
      state: "PENDING",
      risk: "MEDIUM",
      requester_ref: identity.id,
      scope: "仅新平台本地合成账本",
      action: body.capability,
      resource_id: body.resource_id,
      arguments_redacted: body.arguments,
      target_generation: 1,
      created_at: now(),
      expires_at: new Date(Date.now() + 600000).toISOString(),
    });
    this.record(task, "WAITING_APPROVAL");
    const accepted = {
      task_id: task.id,
      state: task.state,
      trace_id: task.trace_id,
      poll_url: `/api/v1/tasks/${task.id}`,
      replayed: false,
    };
    this.keys.set(key, { hash, accepted });
    return accepted;
  }
  record(task: Schema<"Task">, kind: string) {
    task.updated_at = now();
    this.events.push({
      id: uuid(),
      task_id: task.id,
      sequence: this.events.filter((e) => e.task_id === task.id).length + 1,
      kind,
      occurred_at: now(),
      summary: `LOCAL MOCK · ${kind}`,
      trace_id: task.trace_id,
    });
    this.audit.unshift({
      id: uuid(),
      actor_ref: identity.id,
      action: kind,
      resource_ref: task.id,
      result: "LOCAL MOCK",
      created_at: now(),
      trace_id: task.trace_id,
    });
  }
  transition(id: string, state: Schema<"Task">["state"]) {
    const t = this.tasks.find((t) => t.id === id);
    if (!t) throw 404;
    const allowed: Partial<
      Record<Schema<"Task">["state"], Schema<"Task">["state"][]>
    > = {
      WAITING_APPROVAL: ["QUEUED", "CANCELED", "EXPIRED"],
      QUEUED: ["LEASED", "CANCELED"],
      LEASED: ["RUNNING", "NEEDS_RECONCILIATION"],
      RUNNING: ["SUCCEEDED", "FAILED", "NEEDS_RECONCILIATION"],
    };
    if (!allowed[t.state]?.includes(state)) throw 409;
    t.state = state;
    if (state === "CANCELED" || state === "EXPIRED") {
      for (const approval of this.approvals) {
        if (approval.task_id === id && approval.state === "PENDING")
          approval.state = "EXPIRED";
      }
    }
    this.record(t, state);
    return t;
  }
  approve(id: string, reject = false) {
    const a = this.approvals.find((a) => a.id === id);
    if (!a) throw 404;
    if (a.state !== "PENDING") throw 409;
    if (Date.parse(a.expires_at) < Date.now()) {
      a.state = "EXPIRED";
      this.transition(a.task_id, "EXPIRED");
      throw 409;
    }
    if (a.risk !== "MEDIUM") throw 403;
    this.transition(a.task_id, reject ? "CANCELED" : "QUEUED");
    a.state = reject ? "REJECTED" : "APPROVED";
    return a;
  }
  // Pure frontend mock worker; never used outside MSW. No shell, network or backend worker identity.
  async run(
    id: string,
    outcome: "SUCCEEDED" | "FAILED" | "NEEDS_RECONCILIATION" = "SUCCEEDED",
  ) {
    const task = this.transition(id, "LEASED");
    task.generation++;
    const attempt: Schema<"TaskAttemptSummary"> = {
      id: uuid(),
      task_id: id,
      worker_id: "synthetic-worker",
      state: "LEASED",
      generation: task.generation,
    };
    this.attempts.push(attempt);
    await new Promise((r) => setTimeout(r, 300));
    this.transition(id, "RUNNING");
    attempt.state = "RUNNING";
    attempt.started_at = now();
    await new Promise((r) => setTimeout(r, 500));
    this.transition(id, outcome);
    attempt.state = outcome;
    attempt.finished_at = now();
    const approval = this.approvals.find(
      (a) => a.task_id === id && a.state === "APPROVED",
    );
    if (approval) approval.state = "CONSUMED";
    if (outcome === "SUCCEEDED")
      this.artifacts.unshift({
        id: uuid(),
        task_id: id,
        storage_system: "LOCAL MOCK",
        uri: `mock://ledger/${id}/result.json`,
        sha256: null,
        byte_size: null,
      });
  }
}
export const ledger = new Ledger();
