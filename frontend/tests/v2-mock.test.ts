import { afterAll, beforeAll, expect, it } from "vitest";
import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { setupServer } from "msw/node";
import { handlers } from "../src/mocks/handlers";
import { v2Supported } from "../src/mocks/v2";
import operations from "../src/api/generated/operations.json";
import schemas from "../src/mocks/schemas.json";
import { sha256Hex, bytesToBase64 } from "../src/workspace/model";
const server = setupServer(...handlers);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
const ajv = new Ajv({ strict: false });
addFormats(ajv);
ajv.addSchema({ $id: "mw", components: { schemas } });
function valid(name: string, body: unknown) {
  const check = ajv.compile({ $ref: `mw#/components/schemas/${name}` });
  expect(check(body), JSON.stringify(check.errors)).toBe(true);
}
const covered = new Set<string>();
async function call(
  method: string,
  template: string,
  path = template,
  body?: unknown,
  headers: Record<string, string> = {},
  expected?: number,
) {
  const response = await fetch(`http://localhost${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...headers },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  covered.add(`${method.toLowerCase()} ${template}`);
  const op = operations.find(
    (x) => x.path === template && x.method === method.toLowerCase(),
  )!;
  const success = Object.keys(op.responses)
    .map(Number)
    .find((x) => x >= 200 && x < 300);
  expect(
    response.status,
    `${template} ${JSON.stringify(await response.clone().json())}`,
  ).toBe(expected ?? success);
  const shape = (op.responses as Record<string, { $ref?: string } | undefined>)[
    response.status
  ];
  expect(shape, `${template} ${response.status}`).toBeDefined();
  const data = await response.json();
  if (shape?.$ref) valid(shape.$ref.split("/").at(-1)!, data);
  return { response, data };
}

it("keeps all 43 V1 operations and explicitly reports unavailable V2 operations", async () => {
  const v1 = operations.filter((x) => x.x_phase !== "V2" && x.x_phase !== "V3");
  expect(v1).toHaveLength(43);
  for (const op of operations.filter(
    (x) => x.x_phase === "V2" && !v2Supported.has(`${x.method} ${x.path}`),
  )) {
    const path = op.path.replace(/\{[^}]+\}/g, "mock-review-id");
    const { response, data } = await call(
      op.method,
      op.path,
      path,
      op.method === "get" || op.method === "delete" ? undefined : {},
      {},
      path.includes("/workers/") ? 403 : 503,
    );
    expect(response.status).toBe(path.includes("/workers/") ? 403 : 503);
    expect(data.error.code).toBe("mock_v2_unavailable");
  }
});

it("walks schema-validated V2 conversations, sync, uploads and verified downloads", async () => {
  for (const path of [
    "/api/v1/ai/providers",
    "/api/v1/ai/routing-policy",
    "/api/v1/system/contract-meta",
    "/api/v1/clients/devices",
    "/api/v1/clients/sync",
  ])
    expect((await call("GET", path)).response.status).toBe(200);
  const conv = await call("POST", "/api/v1/conversations", undefined, {
    title: "V2 mock review",
  });
  expect(conv.response.status).toBe(201);
  await call("GET", "/api/v1/conversations");
  const base = `/api/v1/conversations/${conv.data.id}`;
  await call("GET", "/api/v1/conversations/{id}", base);
  const msg = await call(
    "POST",
    "/api/v1/conversations/{id}/messages",
    `${base}/messages`,
    { content: "Hello" },
    { "Idempotency-Key": "mock-message-key-0001" },
  );
  expect(msg.response.status).toBe(201);
  const replay = await call(
    "POST",
    "/api/v1/conversations/{id}/messages",
    `${base}/messages`,
    { content: "Hello" },
    { "Idempotency-Key": "mock-message-key-0001" },
  );
  expect(replay.data.id).toBe(msg.data.id);
  expect(replay.data.replayed).toBe(true);
  await call("GET", "/api/v1/conversations/{id}/messages", `${base}/messages`);
  const stream = await fetch(`http://localhost${base}/stream`);
  expect(stream.headers.get("Content-Type")).toContain("text/event-stream");
  expect(await stream.text()).toContain("event: conversation.message");
  covered.add("get /api/v1/conversations/{id}/stream");
  await call("POST", "/api/v1/clients/devices", undefined, {
    device_id: "mock-web",
    platform: "web",
    keystore_kind: "web_httponly_cookie",
    app_version: "2.0",
    os_arch: "browser",
  });
  const state = (await call("GET", "/api/v1/clients/sync")).data;
  const request = {
    device_id: "mock-web",
    expected_revision: state.revision,
    draft_work_items: [{ title: "saved" }],
    ui_preferences: {},
  };
  expect(
    (await call("POST", "/api/v1/clients/sync", undefined, request)).data
      .revision,
  ).toBe(state.revision + 1);
  expect(
    (await call("POST", "/api/v1/clients/sync", undefined, request, {}, 409))
      .response.status,
  ).toBe(409);
  const bytes = new TextEncoder().encode("V2 mock file");
  const sha256 = await sha256Hex(bytes);
  const ticket = (
    await call("POST", "/api/v1/uploads/tickets", undefined, {
      file_name: "note.txt",
      mime_type: "text/plain",
      byte_size: bytes.length,
      sha256,
    })
  ).data;
  const artifact = (
    await call(
      "PUT",
      "/api/v1/uploads/{ticket_id}",
      `/api/v1/uploads/${ticket.ticket_id}`,
      { content_base64: bytesToBase64(bytes) },
    )
  ).data;
  const download = (
    await call(
      "POST",
      "/api/v1/artifacts/{id}/download-ticket",
      `/api/v1/artifacts/${artifact.id}/download-ticket`,
    )
  ).data;
  const content = await call(
    "GET",
    "/api/v1/artifacts/{id}/content",
    `/api/v1/artifacts/${artifact.id}/content`,
    undefined,
    { "X-Download-Ticket": download.ticket_id },
  );
  expect(content.data.sha256).toBe(sha256);
  expect(content.data.content_base64).toBe(bytesToBase64(bytes));
  expect(covered).toEqual(
    new Set(
      operations
        .filter((x) => x.x_phase === "V2")
        .map((x) => `${x.method} ${x.path}`),
    ),
  );
});
