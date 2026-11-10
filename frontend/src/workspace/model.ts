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

// ══════════ V2 Workspace Workflows: Conversations, AI Routing, Uploads/Downloads & Multi-Device Sync ══════════

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(bytes));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    out[i] = binary.charCodeAt(i);
  }
  return out;
}

export async function submitConversationMessage(
  conversationId: string,
  content: string,
  idempotencyKey: string,
  spawnTask: boolean,
  writeMessage: (
    convId: string,
    body: Schema<"ConversationMessageCreate">,
    key: string,
  ) => Promise<Schema<"ConversationMessage">>,
): Promise<Schema<"ConversationMessage">> {
  const trimmed = content.trim();
  if (!trimmed) throw Error("请输入对话内容。");
  if (!idempotencyKey || idempotencyKey.length < 12)
    throw Error("缺少有效的消息幂等键。");
  return await writeMessage(
    conversationId,
    {
      content: trimmed,
      role: "user",
      ...(spawnTask
        ? {
            spawn_capability: "local.simulate",
            spawn_resource_id: "local-ledger",
          }
        : {}),
    },
    idempotencyKey,
  );
}

export async function performVerifiedUpload(
  fileName: string,
  mimeType: string,
  bytes: Uint8Array,
  createTicket: (
    body: Schema<"UploadTicketRequest">,
  ) => Promise<Schema<"UploadTicket">>,
  putUpload: (
    ticketId: string,
    body: Schema<"UploadCompleteRequest">,
  ) => Promise<Schema<"Artifact">>,
  taskId?: string,
): Promise<Schema<"Artifact">> {
  if (!bytes.length) throw Error("不能上传空文件。");
  if (bytes.length > 10 * 1024 * 1024) throw Error("文件超过 10 MiB 限制。");
  if (
    fileName.includes("/") ||
    fileName.includes("\\") ||
    fileName.includes("..")
  )
    throw Error("文件名包含非法路径字符。");
  const digest = await sha256Hex(bytes);
  const ticket = await createTicket({
    file_name: fileName,
    mime_type: mimeType,
    byte_size: bytes.length,
    sha256: digest,
    ...(taskId ? { task_id: taskId } : {}),
  });
  const artifact = await putUpload(ticket.ticket_id, {
    content_base64: bytesToBase64(bytes),
  });
  if (artifact.sha256 && artifact.sha256 !== digest) {
    throw Error("上传后服务端返回的 SHA-256 与本地文件不一致。");
  }
  return artifact;
}

export async function performVerifiedDownload(
  artifactId: string,
  createDownloadTicket: (
    id: string,
  ) => Promise<Schema<"ArtifactDownloadTicket">>,
  fetchContent: (
    id: string,
    ticketId: string,
  ) => Promise<Schema<"ArtifactContentEnvelope">>,
): Promise<{
  bytes: Uint8Array;
  sha256: string;
  mimeType: string;
  disposition: string;
}> {
  const ticket = await createDownloadTicket(artifactId);
  const envelope = await fetchContent(artifactId, ticket.ticket_id);
  const bytes = base64ToBytes(envelope.content_base64);
  const actualSha = await sha256Hex(bytes);
  if (actualSha !== envelope.sha256 || actualSha !== ticket.sha256) {
    throw Error("下载内容 SHA-256 校验失败，已拒绝保存文件。");
  }
  return {
    bytes,
    sha256: actualSha,
    mimeType: envelope.mime_type,
    disposition: envelope.disposition,
  };
}

export async function syncWorkspaceCrossDevice(
  deviceId: string,
  draftWorkItems: Record<string, unknown>[],
  uiPreferences: Record<string, unknown>,
  readSync: () => Promise<Schema<"ClientSyncState">>,
  writeSync: (
    body: Schema<"ClientSyncRequest">,
  ) => Promise<Schema<"ClientSyncState">>,
): Promise<Schema<"ClientSyncState">> {
  const current = await readSync();
  return await writeSync({
    device_id: deviceId,
    expected_revision: current.revision,
    draft_work_items: draftWorkItems,
    ui_preferences: uiPreferences,
  });
}
