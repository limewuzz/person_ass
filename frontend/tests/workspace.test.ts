import { describe, it, expect, vi } from "vitest";
import {
  collectPages,
  submitWork,
  taskBody,
  type Submission,
} from "../src/workspace/model";
import type { Schema } from "../src/api/client";
const draft = (): Submission => ({
  title: "A safe local task",
  kind: "task",
  outcome: "SUCCEEDED",
  key: "unchanged-client-key",
  stage: "ready",
});
const work: Schema<"WorkItem"> = {
  id: "00000000-0000-4000-8000-000000000002",
  title: "A safe local task",
  kind: "task",
  status: "open",
  created_at: "2026-11-09T00:00:00Z",
  created_by: "00000000-0000-4000-8000-000000000001",
};
const accepted: Schema<"TaskAccepted"> = {
  task_id: "00000000-0000-4000-8000-000000000003",
  state: "WAITING_APPROVAL",
  trace_id: "00000000-0000-4000-8000-000000000004",
  poll_url: "/api/v1/tasks/00000000-0000-4000-8000-000000000003",
  replayed: false,
};
describe("user work submission recovery", () => {
  it("retains the same task payload/key after lost acknowledgement and creates one work item", async () => {
    let saved = draft();
    const save = (s: Submission) => {
      saved = s;
    };
    const writeWork = vi.fn(async () => work);
    const writeTask = vi
      .fn()
      .mockRejectedValueOnce(Error("lost ack"))
      .mockResolvedValueOnce({ ...accepted, replayed: true });
    await expect(submitWork(saved, save, writeWork, writeTask)).rejects.toThrow(
      "lost ack",
    );
    expect(saved.stage).toBe("work-saved");
    await submitWork(saved, save, writeWork, writeTask);
    expect(writeWork).toHaveBeenCalledTimes(1);
    expect(writeTask.mock.calls[0]).toEqual(writeTask.mock.calls[1]);
    expect(saved.taskId).toBe(accepted.task_id);
  });
  it("never automatically replays a work-item POST with an unknown outcome", async () => {
    let saved = draft();
    const save = (s: Submission) => {
      saved = s;
    };
    const writeWork = vi.fn(async () => {
        throw Error("connection lost after commit");
      }),
      writeTask = vi.fn();
    await expect(
      submitWork(saved, save, writeWork, writeTask),
    ).rejects.toThrow();
    expect(saved.stage).toBe("unknown-work");
    await expect(submitWork(saved, save, writeWork, writeTask)).rejects.toThrow(
      "核对历史",
    );
    expect(writeWork).toHaveBeenCalledTimes(1);
    expect(writeTask).not.toHaveBeenCalled();
  });
  it("does not call either writer if recovery storage fails before submission", async () => {
    const writeWork = vi.fn(),
      writeTask = vi.fn();
    await expect(
      submitWork(
        draft(),
        () => {
          throw Error("storage denied");
        },
        writeWork,
        writeTask,
      ),
    ).rejects.toThrow("storage denied");
    expect(writeWork).not.toHaveBeenCalled();
    expect(writeTask).not.toHaveBeenCalled();
  });
  it("saves an idea without dispatching a task", async () => {
    const writeTask = vi.fn(),
      writeWork = vi.fn(async () => ({ ...work, kind: "idea" as const }));
    const result = await submitWork(
      { ...draft(), kind: "idea" },
      () => {},
      writeWork,
      writeTask,
    );
    expect(result.stage).toBe("done");
    expect(writeTask).not.toHaveBeenCalled();
  });
  it("cannot route arbitrary prompts, agents, uploads or execution capabilities through TaskCreate", () => {
    const forged = {
      ...draft(),
      workItemId: work.id,
      title: "Run a real command",
      capability: "production.execute",
      resource_id: "legacy-system",
      agent_id: "unapproved-agent",
      arguments: { command: "ignored", upload: "unapproved-path" },
    };
    const body = taskBody(forged);
    expect(body.capability).toBe("local.simulate");
    expect(body.resource_id).toBe("local-ledger");
    expect(body.dry_run).toBe(true);
    expect(body.arguments).toEqual({ outcome: "SUCCEEDED" });
    expect(body).not.toHaveProperty("agent_id");
  });
});
describe("joining paginated related records", () => {
  it("finds records beyond the first page", async () => {
    const read = vi.fn(async (c?: string) =>
      c
        ? { items: ["matching approval"], next_cursor: null }
        : { items: ["other approval"], next_cursor: "second" },
    );
    expect(await collectPages(read)).toEqual([
      "other approval",
      "matching approval",
    ]);
    expect(read.mock.calls).toEqual([[undefined], ["second"]]);
  });
  it("fails visibly on a cursor cycle instead of hanging or claiming empty results", async () => {
    await expect(
      collectPages(async () => ({ items: [], next_cursor: "repeated" })),
    ).rejects.toThrow("游标重复");
  });
  it("does not convert an authorization error on a later page into partial success", async () => {
    const read = vi
      .fn()
      .mockResolvedValueOnce({ items: [1], next_cursor: "private" })
      .mockRejectedValueOnce(Error("forbidden"));
    await expect(collectPages(read)).rejects.toThrow("forbidden");
  });
});
