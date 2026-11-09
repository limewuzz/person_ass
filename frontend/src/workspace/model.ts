import type { Schema } from "../api/client";

export const taskStates: Record<Schema<"Task">["state"], string> = {
  DRAFT: "草稿",
  VALIDATING: "检查中",
  WAITING_APPROVAL: "等待你确认",
  QUEUED: "已排队",
  LEASED: "已领取",
  RUNNING: "进行中",
  SUCCEEDED: "已完成",
  FAILED: "执行失败",
  CANCELED: "已取消",
  EXPIRED: "已过期",
  NEEDS_RECONCILIATION: "需要人工核对",
};
export const terminal = new Set([
  "SUCCEEDED",
  "FAILED",
  "CANCELED",
  "EXPIRED",
  "NEEDS_RECONCILIATION",
]);

// Follow server cursors before joining tasks/approvals/results; never silently
// report "no result" merely because it is on a later page.
export async function collectPages<T>(
  read: (
    cursor?: string,
  ) => Promise<{ items: T[]; next_cursor?: string | null }>,
) {
  const items: T[] = [],
    seen = new Set<string>();
  let cursor: string | undefined;
  do {
    const page = await read(cursor);
    items.push(...page.items);
    cursor = page.next_cursor ?? undefined;
    if (cursor && seen.has(cursor)) throw Error("目录游标重复，请刷新后重试。");
    if (cursor) seen.add(cursor);
    if (items.length > 20000)
      throw Error("目录超过工作台读取上限，请前往管理后台筛选。");
  } while (cursor);
  return items;
}

export type Draft = {
  title: string;
  kind: "task" | "idea" | "paper";
  outcome: "SUCCEEDED" | "FAILED" | "NEEDS_RECONCILIATION";
};
export type Submission = Draft & {
  key: string;
  workItemId?: string;
  taskId?: string;
  stage: "ready" | "creating-work" | "unknown-work" | "work-saved" | "done";
};
export function taskBody(s: Submission): Schema<"TaskCreate"> {
  if (!s.workItemId) throw Error("工作项尚未保存");
  return {
    work_item_id: s.workItemId,
    capability: "local.simulate",
    resource_id: "local-ledger",
    arguments: { outcome: s.outcome },
    dry_run: true,
    origin: { channel: "web", source_ref: "user-workspace" },
  };
}
export const draftKey = "mw-workspace-draft-v1",
  journalKey = "mw-workspace-submission-v1";
export function readDraft(): Draft {
  try {
    const v: unknown = JSON.parse(sessionStorage.getItem(draftKey) ?? "null");
    if (
      v &&
      typeof v === "object" &&
      "title" in v &&
      typeof v.title === "string" &&
      "kind" in v &&
      ["task", "idea", "paper"].includes(String(v.kind)) &&
      "outcome" in v &&
      ["SUCCEEDED", "FAILED", "NEEDS_RECONCILIATION"].includes(
        String(v.outcome),
      )
    )
      return {
        title: v.title.slice(0, 200),
        kind: v.kind as Draft["kind"],
        outcome: v.outcome as Draft["outcome"],
      };
  } catch {
    /* Storage may be unavailable; no silent submission takes place. */
  }
  return { title: "", kind: "task", outcome: "SUCCEEDED" };
}
export function readSubmission(): Submission | null {
  try {
    const v = JSON.parse(
      sessionStorage.getItem(journalKey) ?? "null",
    ) as Submission | null;
    if (
      !v ||
      typeof v.title !== "string" ||
      typeof v.key !== "string" ||
      !["task", "idea", "paper"].includes(v.kind) ||
      !["SUCCEEDED", "FAILED", "NEEDS_RECONCILIATION"].includes(v.outcome) ||
      ![
        "ready",
        "creating-work",
        "unknown-work",
        "work-saved",
        "done",
      ].includes(v.stage)
    )
      return null;
    if (
      v.workItemId !== undefined &&
      (typeof v.workItemId !== "string" ||
        !/^[a-f0-9-]{36}$/.test(v.workItemId))
    )
      return null;
    if (v.stage === "creating-work") v.stage = "unknown-work";
    return v;
  } catch {
    return null;
  }
}

// An interrupted work-item POST cannot safely be replayed: that operation has no
// idempotency guarantee in the frozen contract. Task POST does, so retain its key
// and immutable payload when the acknowledgement is lost.
export async function submitWork(
  s: Submission,
  save: (s: Submission) => void,
  writeWork: (body: Schema<"WorkItemCreate">) => Promise<Schema<"WorkItem">>,
  writeTask: (
    body: Schema<"TaskCreate">,
    key: string,
  ) => Promise<Schema<"TaskAccepted">>,
) {
  if (s.stage === "creating-work" || s.stage === "unknown-work")
    throw Error("工作项提交结果未知，请先核对历史，避免重复创建。");
  if (s.stage === "done") return s;
  let next = { ...s };
  if (!next.workItemId) {
    next.stage = "creating-work";
    save(next);
    try {
      const item = await writeWork({
        title: s.title.trim(),
        kind: s.kind,
        source_system: "magicworkshop-workspace",
      });
      next = { ...next, workItemId: item.id, stage: "work-saved" };
      save(next);
    } catch (e) {
      // Even a transport error may occur after the server committed the record.
      next.stage = "unknown-work";
      save(next);
      throw e;
    }
  }
  if (next.kind === "task") {
    const accepted = await writeTask(taskBody(next), next.key);
    next = { ...next, taskId: accepted.task_id };
  }
  next.stage = "done";
  save(next);
  return next;
}

export function exportRecord(value: unknown, name: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
