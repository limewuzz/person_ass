import { afterAll, beforeAll, expect, it } from "vitest";
import Ajv from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { setupServer } from "msw/node";
import { handlers } from "../src/mocks/handlers";
import schemas from "../src/mocks/schemas.json";
const server = setupServer(...handlers);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
const ajv = new Ajv({ strict: false });
addFormats(ajv);
ajv.addSchema({ $id: "mw", components: { schemas } });
async function call(
  path: string,
  body?: unknown,
  key = "v3-unit-intent-123456",
) {
  return fetch("http://localhost/api/v1" + path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}
const input = {
  recipe_id: "paper",
  title: "One paper",
  input: "offline note",
  mode: "SIMULATE",
  targets: ["archive", "paper", "reminder", "experiment"],
  origin: { channel: "web" },
};
it("four recipes and one aggregate approval preserve the shared item and dependencies", async () => {
  const recipes = await (await call("/recipes")).json();
  expect(recipes.items).toHaveLength(4);
  const first = await (await call("/fanouts", input)).json();
  const validate = ajv.compile({ $ref: "mw#/components/schemas/FanoutPlan" });
  expect(validate(first), JSON.stringify(validate.errors)).toBe(true);
  expect((await (await call("/fanouts", input)).json()).id).toBe(first.id);
  expect((await call("/fanouts", { ...input, title: "changed" })).status).toBe(
    409,
  );
  expect(first.deliveries).toHaveLength(5);
  const low = await (await call(`/fanouts/${first.id}/simulate`, {})).json();
  expect(
    low.deliveries.find((d: { step_id: string }) => d.step_id === "experiment")
      .attempts,
  ).toBe(0);
  await call(`/fanouts/${first.id}/decision`, { decision: "approved" });
  for (let i = 0; i < 4; i++) await call(`/fanouts/${first.id}/simulate`, {});
  const final = await (await call(`/fanouts/${first.id}`)).json();
  expect(final.status).toBe("SUCCEEDED");
  expect(final.work_item_id).toBe(first.work_item_id);
  expect(
    final.deliveries.every((d: { attempts: number }) => d.attempts === 1),
  ).toBe(true);
  expect(validate(final), JSON.stringify(validate.errors)).toBe(true);
});
it("unknown execution requires a revision-bound reason and verified receipt", async () => {
  const p = await (
    await call(
      "/fanouts",
      { ...input, recipe_id: "wechat", targets: ["reminder"] },
      "v3-unit-unknown-123456",
    )
  ).json();
  const unknown = await (
    await call(`/fanouts/${p.id}/simulate`, { outcome: "UNKNOWN" })
  ).json();
  const d = unknown.deliveries[0];
  const path = `/fanouts/${p.id}/deliveries/${d.id}/reconcile`;
  expect(
    (
      await call(path, {
        expected_generation: d.generation + 1,
        resolution: "FAIL",
        reason: "Confirmed definitive failure",
      })
    ).status,
  ).toBe(409);
  expect(
    (
      await call(path, {
        expected_generation: d.generation,
        resolution: "ACCEPT_RECEIPT",
        reason: "Confirmed completed receipt",
      })
    ).status,
  ).toBe(400);
  const accepted = await (
    await call(path, {
      expected_generation: d.generation,
      resolution: "ACCEPT_RECEIPT",
      reason: "Confirmed completed receipt",
      receipt: {
        uri: "mock://verified",
        sha256: "a".repeat(64),
        source_mode: "MOCK",
      },
    })
  ).json();
  expect(accepted.status).toBe("SUCCEEDED");
});
it("browser mock cannot invoke workers or webhook, and LIVE cannot simulate", async () => {
  expect(
    (await call("/workers/relay/outbox/claim", { mode: "SIMULATE" })).status,
  ).toBe(403);
  expect((await call("/webhooks/trigger", input)).status).toBe(403);
  const p = await (
    await call("/fanouts", { ...input, mode: "LIVE" }, "v3-unit-live-123456")
  ).json();
  expect(p.availability).toBe("UNAVAILABLE");
  expect((await call(`/fanouts/${p.id}/simulate`, {})).status).toBe(403);
});
