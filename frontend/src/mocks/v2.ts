// Explicit local simulations. Unmodeled V2 operations return UNAVAILABLE,
// rather than reusing a V1 list/detail payload with the wrong schema.
import { HttpResponse } from "msw";
import type { Schema } from "../api/client";
import { identity, now, uuid, meta } from "./fixtures";
import { fanoutResponse, stableJson } from "./fanout";
import { ledger } from "./engine";
import contract from "../api/generated/contract.json" with { type: "json" };
import { sha256Hex, base64ToBytes } from "../workspace/model";

export const v2Supported = new Set([
  "get /api/v1/ai/providers",
  "get /api/v1/ai/routing-policy",
  "get /api/v1/conversations",
  "post /api/v1/conversations",
  "get /api/v1/conversations/{id}",
  "get /api/v1/conversations/{id}/messages",
  "post /api/v1/conversations/{id}/messages",
  "get /api/v1/conversations/{id}/stream",
  "get /api/v1/clients/devices",
  "post /api/v1/clients/devices",
  "get /api/v1/clients/sync",
  "post /api/v1/clients/sync",
  "post /api/v1/uploads/tickets",
  "put /api/v1/uploads/{ticket_id}",
  "post /api/v1/artifacts/{id}/download-ticket",
  "get /api/v1/artifacts/{id}/content",
  "get /api/v1/system/contract-meta",
]);
const conversations = new Map<string, Schema<"Conversation">>();
const messages = new Map<string, Schema<"ConversationMessage">[]>();
const idem = new Map<
  string,
  { content: string; message: Schema<"ConversationMessage"> }
>();
const devices = new Map<string, Schema<"ClientDevice">>();
const tickets = new Map<string, Schema<"UploadTicketRequest">>();
const contents = new Map<
  string,
  { base64: string; sha256: string; mime: string; name: string }
>();
const downloads = new Map<string, string>();
let sync: Schema<"ClientSyncState"> = {
  owner_sub: identity.id,
  revision: 0,
  cursor: "sync-cursor-0",
  draft_work_items: [],
  ui_preferences: {},
  updated_at: now(),
};
function fail(status: number, code: string) {
  return HttpResponse.json(
    { error: { code, message: "Local V2 simulation" }, trace_id: uuid() },
    { status },
  );
}
export async function v2Response(
  method: string,
  path: string,
  request: Request,
  params: Record<string, unknown>,
) {
  const operation = `${method} ${path}`;
  const rawBody = ["post", "put"].includes(method) ? await request.text() : "";
  const body = rawBody ? JSON.parse(rawBody) : {};
  const id = String(params.id ?? "");
  if (
    path === "/api/v1/work-items/{id}/dispatch" &&
    method === "post" &&
    body.recipe_id
  ) {
    if (!ledger.workItems.some((w) => w.id === id))
      return fail(404, "not_found");
    const response = await fanoutResponse(
      "post",
      "/api/v1/fanouts",
      new Request(request.url, {
        method: "POST",
        headers: request.headers,
        body: rawBody,
      }),
      { work_item_id: id },
    );
    return new HttpResponse(await response.text(), {
      status: response.status === 201 ? 202 : response.status,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (!v2Supported.has(operation))
    return fail(path.includes("/workers/") ? 403 : 503, "mock_v2_unavailable");
  if (path === "/api/v1/ai/providers")
    return HttpResponse.json({
      items: [],
      next_cursor: null,
      source_meta: meta(),
    });
  if (path === "/api/v1/ai/routing-policy")
    return HttpResponse.json({
      default_model_id: "model.local-simulation",
      fallback_model_id: null,
      task_routes: {},
      updated_at: now(),
      source_meta: meta(),
    });
  if (path === "/api/v1/system/contract-meta")
    return HttpResponse.json({
      contract_version: contract.version,
      openapi_sha256: contract.contract_sha256,
      total_paths: 89,
      total_operations: 106,
      baseline_v1_paths: 41,
      baseline_v1_operations: 43,
      workflows_ready: Object.fromEntries(
        [
          "platform_core",
          "ai_infrastructure",
          "agent_os",
          "compute_resources",
          "multi_platform_clients",
          "data_integrations",
          "testing_and_delivery",
        ].map((k) => [k, false]),
      ),
      checked_at: now(),
    });
  if (path === "/api/v1/conversations") {
    if (method === "get")
      return HttpResponse.json({
        items: [...conversations.values()],
        next_cursor: null,
      });
    if (!body.title) return fail(400, "title_required");
    const item: Schema<"Conversation"> = {
      id: uuid(),
      title: body.title,
      owner_sub: identity.id,
      agent_id: null,
      work_item_id: null,
      message_count: 0,
      created_at: now(),
      updated_at: now(),
    };
    conversations.set(item.id, item);
    messages.set(item.id, []);
    return HttpResponse.json(item, { status: 201 });
  }
  if (path.startsWith("/api/v1/conversations/")) {
    const conv = conversations.get(id);
    if (!conv) return fail(404, "not_found");
    if (path.endsWith("/stream"))
      return new HttpResponse(
        `retry: 15000\nid: mock-${id}\nevent: conversation.message\ndata: {}\n\n`,
        { headers: { "Content-Type": "text/event-stream" } },
      );
    if (path.endsWith("/messages")) {
      const items = messages.get(id)!;
      if (method === "get")
        return HttpResponse.json({ items, next_cursor: null });
      const key = request.headers.get("Idempotency-Key");
      if (!key || key.length < 12 || !body.content)
        return fail(400, "message_required");
      const previous = idem.get(`${id}:${key}`);
      if (previous)
        return previous.content === stableJson(body)
          ? HttpResponse.json(
              { ...previous.message, replayed: true },
              { status: 201 },
            )
          : fail(409, "idempotency_conflict");
      const item: Schema<"ConversationMessage"> = {
        id: uuid(),
        conversation_id: id,
        sequence: items.length + 1,
        role: "user",
        content: body.content,
        spawned_task_id: null,
        approval_id: null,
        created_at: now(),
        replayed: false,
      };
      if (body.fanout) {
        if (body.spawn_capability)
          return fail(400, "fanout_and_spawn_mutually_exclusive");
        const headers = new Headers(request.headers);
        headers.set("Idempotency-Key", `conversation:${id}:${key}`);
        const response = await fanoutResponse(
          "post",
          "/api/v1/fanouts",
          new Request(request.url, {
            method: "POST",
            headers,
            body: JSON.stringify(body.fanout),
          }),
          conv.work_item_id ? { work_item_id: conv.work_item_id } : {},
        );
        if (response.status !== 201) return response;
        item.fanout = await response.json();
        conv.work_item_id = item.fanout!.work_item_id;
      }
      items.push(item);
      idem.set(`${id}:${key}`, { content: stableJson(body), message: item });
      conv.message_count++;
      return HttpResponse.json(item, { status: 201 });
    }
    return HttpResponse.json(conv);
  }
  if (path === "/api/v1/clients/devices") {
    if (method === "get")
      return HttpResponse.json({
        items: [...devices.values()],
        next_cursor: null,
      });
    if (!body.device_id || body.keystore_kind !== "web_httponly_cookie")
      return fail(400, "invalid_device");
    const dev = {
      ...body,
      owner_sub: identity.id,
      revoked: false,
      wipe_pending: false,
      updated_at: now(),
    };
    devices.set(dev.device_id, dev);
    return HttpResponse.json(dev, { status: 201 });
  }
  if (path === "/api/v1/clients/sync") {
    if (method === "post") {
      if (!devices.has(body.device_id)) return fail(403, "device_required");
      if (body.expected_revision !== sync.revision)
        return fail(409, "sync_conflict");
      sync = {
        owner_sub: identity.id,
        revision: sync.revision + 1,
        cursor: `sync-cursor-${sync.revision + 1}`,
        draft_work_items: body.draft_work_items ?? [],
        ui_preferences: body.ui_preferences ?? {},
        updated_at: now(),
      };
    }
    return HttpResponse.json(sync);
  }
  if (path === "/api/v1/uploads/tickets") {
    if (
      !body.file_name ||
      !body.sha256 ||
      !body.byte_size ||
      body.byte_size > 10 * 1024 * 1024
    )
      return fail(400, "invalid_upload");
    const ticket: Schema<"UploadTicket"> = {
      ticket_id: uuid(),
      upload_url: "/api/v1/uploads/local-mock",
      expires_at: new Date(Date.now() + 600000).toISOString(),
      max_bytes: body.byte_size,
      expected_sha256: body.sha256,
      state: "ISSUED",
    };
    tickets.set(ticket.ticket_id, body);
    return HttpResponse.json(ticket, { status: 201 });
  }
  if (path === "/api/v1/uploads/{ticket_id}") {
    const ticket = tickets.get(String(params.ticket_id));
    if (!ticket) return fail(404, "not_found");
    const bytes = base64ToBytes(body.content_base64 ?? "");
    if (
      bytes.length !== ticket.byte_size ||
      (await sha256Hex(bytes)) !== ticket.sha256
    )
      return fail(400, "upload_integrity_mismatch");
    const artifact: Schema<"Artifact"> = {
      id: uuid(),
      task_id: null,
      storage_system: "LOCAL_MOCK",
      uri: `mock://uploads/${uuid()}/${ticket.file_name}`,
      sha256: ticket.sha256,
      byte_size: bytes.length,
    };
    ledger.artifacts.push(artifact);
    contents.set(artifact.id, {
      base64: body.content_base64,
      sha256: ticket.sha256,
      mime: ticket.mime_type,
      name: ticket.file_name,
    });
    return HttpResponse.json(artifact);
  }
  const content = contents.get(id);
  if (!content) return fail(404, "not_found");
  if (method === "post") {
    const ticket = uuid();
    downloads.set(ticket, id);
    return HttpResponse.json({
      ticket_id: ticket,
      artifact_id: id,
      download_url: `/api/v1/artifacts/${id}/content`,
      disposition: `attachment; filename="${content.name}"`,
      expires_at: new Date(Date.now() + 300000).toISOString(),
      sha256: content.sha256,
      byte_size: base64ToBytes(content.base64).length,
    });
  }
  if (downloads.get(request.headers.get("X-Download-Ticket") ?? "") !== id)
    return fail(403, "download_ticket_required");
  return HttpResponse.json({
    artifact_id: id,
    content_base64: content.base64,
    sha256: content.sha256,
    byte_size: base64ToBytes(content.base64).length,
    mime_type: content.mime,
    disposition: `attachment; filename="${content.name}"`,
  });
}
