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

import {
  performVerifiedDownload,
  performVerifiedUpload,
  submitConversationMessage,
  syncWorkspaceCrossDevice,
  bytesToBase64,
  sha256Hex,
} from "../src/workspace/model";

describe("V2 workspace workflows: conversations, uploads/downloads, and multi-device sync", () => {
  it("submits conversation messages with idempotency key and optional task spawn", async () => {
    const writeMsg = vi.fn(async (cid, body, key) => ({
      id: "msg-1",
      conversation_id: cid,
      sequence: 1,
      role: body.role ?? "user",
      content: body.content,
      spawned_task_id: body.spawn_capability ? accepted.task_id : null,
      approval_id: body.spawn_capability ? "apr-1" : null,
      created_at: "2026-11-10T00:00:00Z",
      replayed: false,
    }));
    const res = await submitConversationMessage(
      "conv-1",
      "请执行本地模拟验证",
      "idem-conv-msg-0001",
      true,
      writeMsg,
    );
    expect(res.spawned_task_id).toBe(accepted.task_id);
    expect(writeMsg).toHaveBeenCalledWith(
      "conv-1",
      {
        content: "请执行本地模拟验证",
        role: "user",
        spawn_capability: "local.simulate",
        spawn_resource_id: "local-ledger",
      },
      "idem-conv-msg-0001",
    );
  });

  it("verifies SHA-256 digest on both upload and download and rejects tampered content", async () => {
    const raw = new TextEncoder().encode("# V2 Artifact Content");
    const expectedSha = await sha256Hex(raw);
    const createTicket = vi.fn(async (body) => ({
      ticket_id: "tk-1",
      upload_url: "/api/v1/uploads/tk-1",
      expires_at: "2026-11-10T01:00:00Z",
      max_bytes: body.byte_size,
      expected_sha256: body.sha256,
      state: "ISSUED" as const,
      artifact_id: null,
    }));
    const putUpload = vi.fn(async () => ({
      id: "art-1",
      task_id: accepted.task_id,
      storage_system: "LOCAL_UPLOAD_VAULT",
      uri: "memory://uploads/art-1/note.md",
      sha256: expectedSha,
      byte_size: raw.length,
    }));
    const uploaded = await performVerifiedUpload(
      "note.md",
      "text/markdown",
      raw,
      createTicket,
      putUpload,
    );
    expect(uploaded.sha256).toBe(expectedSha);

    const dl = await performVerifiedDownload(
      "art-1",
      async () => ({
        ticket_id: "dl-1",
        artifact_id: "art-1",
        download_url: "/api/v1/artifacts/art-1/content?ticket=dl-1",
        expires_at: "2026-11-10T01:00:00Z",
        sha256: expectedSha,
        byte_size: raw.length,
        disposition: 'attachment; filename="note.md"',
      }),
      async () => ({
        artifact_id: "art-1",
        sha256: expectedSha,
        byte_size: raw.length,
        mime_type: "text/markdown",
        disposition: 'attachment; filename="note.md"',
        content_base64: bytesToBase64(raw),
      }),
    );
    expect(dl.sha256).toBe(expectedSha);
    expect(new TextDecoder().decode(dl.bytes)).toBe("# V2 Artifact Content");

    // Tampered download payload must be rejected
    await expect(
      performVerifiedDownload(
        "art-1",
        async () => ({
          ticket_id: "dl-2",
          artifact_id: "art-1",
          download_url: "/api/v1/artifacts/art-1/content?ticket=dl-2",
          expires_at: "2026-11-10T01:00:00Z",
          sha256: expectedSha,
          byte_size: raw.length,
          disposition: 'attachment; filename="note.md"',
        }),
        async () => ({
          artifact_id: "art-1",
          sha256: expectedSha,
          byte_size: raw.length,
          mime_type: "text/markdown",
          disposition: 'attachment; filename="note.md"',
          content_base64: bytesToBase64(new TextEncoder().encode("tampered")),
        }),
      ),
    ).rejects.toThrow("SHA-256");
  });

  it("synchronizes cross-device workspace state using optimistic revision CAS", async () => {
    const readSync = vi.fn(async () => ({
      owner_sub: "u1",
      revision: 3,
      cursor: "sync-cursor-3",
      draft_work_items: [],
      ui_preferences: { theme: "system" },
      updated_at: "2026-11-10T00:00:00Z",
    }));
    const writeSync = vi.fn(async (body) => ({
      owner_sub: "u1",
      revision: body.expected_revision + 1,
      cursor: `sync-cursor-${body.expected_revision + 1}`,
      draft_work_items: body.draft_work_items,
      ui_preferences: body.ui_preferences,
      updated_at: "2026-11-10T00:01:00Z",
    }));
    const synced = await syncWorkspaceCrossDevice(
      "web-workspace-primary",
      [{ title: "Synced draft" }],
      { theme: "dark" },
      readSync,
      writeSync,
    );
    expect(synced.revision).toBe(4);
    expect(writeSync).toHaveBeenCalledWith({
      device_id: "web-workspace-primary",
      expected_revision: 3,
      draft_work_items: [{ title: "Synced draft" }],
      ui_preferences: { theme: "dark" },
    });
  });
});
