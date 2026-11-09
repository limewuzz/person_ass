import { describe, it, expect } from "vitest";
import { Ledger } from "../src/mocks/engine";
import type { Schema } from "../src/api/client";
const body: Schema<"TaskCreate"> = {
  resource_id: "local-ledger",
  capability: "local.simulate",
  arguments: {},
  origin: { channel: "web" },
  dry_run: true,
};
describe("pure local mock ledger", () => {
  it("replays 100 identical requests, rejects changed payload", async () => {
    const l = new Ledger();
    const ids = await Promise.all(
      Array.from({ length: 100 }, () =>
        Promise.resolve(l.create(body, "same")),
      ),
    );
    expect(new Set(ids.map((r) => r.task_id)).size).toBe(1);
    expect(l.tasks).toHaveLength(1);
    expect(() =>
      l.create({ ...body, arguments: { changed: true } }, "same"),
    ).toThrow();
  });
  it("refuses production targets and illegal transitions", () => {
    const l = new Ledger();
    expect(() =>
      l.create({ ...body, resource_id: "old-production" }, "k"),
    ).toThrow();
    const r = l.create(body, "k");
    expect(() => l.transition(r.task_id, "SUCCEEDED")).toThrow();
    expect(l.tasks[0].state).toBe("WAITING_APPROVAL");
  });
  it("walks approval, worker, result, trace, artifacts", async () => {
    const l = new Ledger();
    const r = l.create(body, "k");
    l.approve(l.approvals[0].id);
    await l.run(r.task_id);
    expect(l.tasks[0].state).toBe("SUCCEEDED");
    expect(l.attempts[0].state).toBe("SUCCEEDED");
    expect(l.events.map((e) => e.kind)).toEqual([
      "WAITING_APPROVAL",
      "QUEUED",
      "LEASED",
      "RUNNING",
      "SUCCEEDED",
    ]);
    expect(l.artifacts[0].task_id).toBe(r.task_id);
    expect(l.events.every((e) => e.trace_id === r.trace_id)).toBe(true);
    expect(l.approvals[0].state).toBe("CONSUMED");
  });
  it.each(["FAILED", "NEEDS_RECONCILIATION"] as const)(
    "supports %s without fake artifacts",
    async (outcome) => {
      const l = new Ledger();
      l.create(body, "k");
      l.approve(l.approvals[0].id);
      await l.run(l.tasks[0].id, outcome);
      expect(l.tasks[0].state).toBe(outcome);
      expect(l.artifacts).toHaveLength(0);
    },
  );
  it("cancellation invalidates pending approval", () => {
    const l = new Ledger();
    const task = l.create(body, "cancel");
    l.transition(task.task_id, "CANCELED");
    expect(l.approvals[0].state).toBe("EXPIRED");
    expect(() => l.approve(l.approvals[0].id)).toThrow();
  });
  it("expires approvals and forbids second consumption", () => {
    const l = new Ledger();
    l.create(body, "k");
    l.approvals[0].expires_at = "2000-01-01T00:00:00Z";
    expect(() => l.approve(l.approvals[0].id)).toThrow();
    expect(l.tasks[0].state).toBe("EXPIRED");
    const other = new Ledger();
    other.create(body, "k");
    other.approve(other.approvals[0].id, true);
    expect(() => other.approve(other.approvals[0].id)).toThrow();
    expect(other.tasks[0].state).toBe("CANCELED");
  });
});
