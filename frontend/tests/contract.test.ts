import { beforeAll, afterAll, afterEach, it, expect } from "vitest";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { setupServer } from "msw/node";
import { handlers, control } from "../src/mocks/handlers";
import { ledger } from "../src/mocks/engine";
import {
  nodes,
  resources,
  agents,
  capabilities,
  integrations,
  catalog,
  bootstrap,
  meta,
  identity,
} from "../src/mocks/fixtures";
import schemas from "../src/mocks/schemas.json";
import operations from "../src/api/generated/operations.json";
const ajv = new Ajv2020({ strict: false });
addFormats(ajv);
ajv.addSchema({ $id: "mw", components: { schemas } });
function valid(name: string, data: unknown) {
  const check = ajv.compile({ $ref: `mw#/components/schemas/${name}` });
  expect(check(data), JSON.stringify(check.errors)).toBe(true);
}
const server = setupServer(...handlers);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterAll(() => server.close());
afterEach(() => {
  control.scenario = "normal";
});
it("validates typed synthetic seeds against unchanged candidate", () => {
  nodes.forEach((n) => valid("Node", n));
  resources.forEach((n) => valid("Resource", n));
  agents.forEach((n) => valid("Agent", n));
  capabilities.forEach((n) => valid("Capability", n));
  integrations.forEach((n) => valid("Integration", n));
  valid("Me", identity);
  valid("DataSourceMeta", meta());
  valid("UIBootstrap", bootstrap());
  for (const key of [
    "models",
    "workflows",
    "network/links",
    "projects",
    "compute/runs",
    "knowledge",
  ])
    valid("DisplayRecordList", catalog(key));
});
it("covers every candidate operation with schema validated success or explicit forbidden worker behavior", async () => {
  const work = await fetch("http://localhost/api/v1/work-items", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Mock work", kind: "task" }),
  }).then((r) => {
    expect(r.status).toBe(201);
    return r.json();
  });
  valid("WorkItem", work);
  const accepted = await fetch("http://localhost/api/v1/tasks", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": "contract-k",
    },
    body: JSON.stringify({
      work_item_id: work.id,
      resource_id: "local-ledger",
      capability: "local.simulate",
      arguments: {},
      origin: { channel: "web" },
      dry_run: true,
    }),
  }).then((r) => r.json());
  valid("TaskAccepted", accepted);
  const task = ledger.tasks[0],
    approval = ledger.approvals[0];
  await ledger.approve(approval.id);
  await ledger.run(task.id);
  for (const op of operations) {
    if (op.method === "post") continue;
    let path = op.path;
    if (path.includes("{id}")) {
      const id = path.includes("/tasks/")
        ? task.id
        : path.includes("/nodes/")
          ? "us"
          : path.includes("/resources/")
            ? "service-us"
            : path.includes("/agents/")
              ? "agent-1"
              : path.includes("/work-items/")
                ? work.id
                : path.includes("/approvals/")
                  ? approval.id
                  : ledger.artifacts[0].id;
      path = path.replace("{id}", id);
    }
    const response = await fetch(`http://localhost${path}`);
    if (path === "/api/v1/health/ready") {
      expect(response.status).toBe(503);
      valid("ReadinessStatus", await response.json());
      continue;
    }
    expect(response.status, path).toBe(200);
    if (path === "/api/v1/events") {
      expect(response.headers.get("Content-Type")).toContain(
        "text/event-stream",
      );
      expect(await response.text()).toContain("id:");
      continue;
    }
    const schema = Object.values(op.responses)[0] as { $ref?: string };
    const data: unknown = await response.json();
    if (schema.$ref) valid(schema.$ref.split("/").at(-1)!, data);
  }
  for (const op of operations.filter(
    (o) => o.method === "post" && o.path.includes("/workers/"),
  )) {
    const response = await fetch(
      `http://localhost${op.path.replace("{worker_id}", "mock-worker").replace("{task_id}", task.id)}`,
      { method: "POST", body: "{}" },
    );
    expect(response.status).toBe(403);
    valid("Error", await response.json());
  }
});
it.each(["401", "403", "404", "409", "503"] as const)(
  "redacts %s failures and does not promote mock source",
  async (status) => {
    control.scenario = status;
    const r = await fetch("http://localhost/api/v1/nodes");
    expect(r.status).toBe(Number(status));
    valid("Error", await r.json());
  },
);
it("cursor pages are disjoint, stale remains independent of health", async () => {
  let r = await fetch("http://localhost/api/v1/nodes?limit=2").then((r) =>
    r.json(),
  );
  expect(r.items).toHaveLength(2);
  const next = await fetch(
    `http://localhost/api/v1/nodes?cursor=${r.next_cursor}&limit=2`,
  ).then((r) => r.json());
  expect(next.items[0].id).not.toBe(r.items[0].id);
  control.scenario = "stale";
  r = await fetch("http://localhost/api/v1/nodes").then((r) => r.json());
  expect(r.items[0].stale).toBe(true);
  expect(r.items[0].health).toBe("unknown");
});
it("HTTP mutation responses match candidate, and canceled approval cannot be reused", async () => {
  const make = async (key: string) =>
    fetch("http://localhost/api/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": key },
      body: JSON.stringify({
        resource_id: "local-ledger",
        capability: "local.simulate",
        arguments: {},
        origin: { channel: "web" },
      }),
    }).then((r) => r.json());
  const a = await make("http-approve");
  const approval = ledger.approvals.find((x) => x.task_id === a.task_id)!;
  let response = await fetch(
    `http://localhost/api/v1/approvals/${approval.id}/approve`,
    { method: "POST" },
  );
  expect(response.status).toBe(200);
  valid("Approval", await response.json());
  const b = await make("http-reject");
  const rejected = ledger.approvals.find((x) => x.task_id === b.task_id)!;
  response = await fetch(
    `http://localhost/api/v1/approvals/${rejected.id}/reject`,
    { method: "POST" },
  );
  expect(response.status).toBe(200);
  valid("Approval", await response.json());
  expect(ledger.tasks.find((t) => t.id === b.task_id)?.state).toBe("CANCELED");
  const c = await make("http-cancel");
  const canceled = ledger.approvals.find((x) => x.task_id === c.task_id)!;
  response = await fetch(`http://localhost/api/v1/tasks/${c.task_id}/cancel`, {
    method: "POST",
  });
  expect(response.status).toBe(202);
  valid("Task", await response.json());
  response = await fetch(
    `http://localhost/api/v1/approvals/${canceled.id}/approve`,
    { method: "POST" },
  );
  expect(response.status).toBe(409);
  valid("Error", await response.json());
  await new Promise((r) => setTimeout(r, 900));
  expect(ledger.tasks.find((t) => t.id === a.task_id)?.state).toBe("SUCCEEDED");
});
it("consumes actual corrected backend exported fixtures under the same frozen schema", async () => {
  const { readFileSync } = await import("node:fs");
  const names: Record<string, string> = {
    "ui-bootstrap": "UIBootstrap",
    "dashboard-summary": "DashboardSummary",
    "events-history": "AuditHistoryList",
    workflows: "DisplayRecordList",
    models: "DisplayRecordList",
    nodes: "NodeList",
    integrations: "IntegrationList",
    artifacts: "ArtifactList",
  };
  for (const [file, schema] of Object.entries(names))
    valid(
      schema,
      JSON.parse(
        readFileSync(`integration/corrected-fixtures/${file}.json`, "utf8"),
      ),
    );
});
