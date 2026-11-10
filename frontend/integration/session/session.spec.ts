import { test, expect, type BrowserContext } from "@playwright/test";
import { readFileSync, existsSync, statSync } from "node:fs";
import { resolve, extname } from "node:path";
import {
  bootstrap,
  capabilities,
  identity,
  meta,
  now,
} from "../../src/mocks/fixtures";
const origin = "https://workspace.test",
  root = resolve("dist");
const tid = "00000000-0000-4000-8000-000000000011",
  wid = "00000000-0000-4000-8000-000000000012";
async function host(context: BrowserContext, authorized: boolean) {
  const requests: { path: string; method: string }[] = [],
    external: string[] = [];
  if (authorized)
    await context.addCookies([
      {
        name: "session_fixture",
        value: "synthetic-cookie",
        url: origin,
        httpOnly: true,
        secure: true,
        sameSite: "Strict",
      },
    ]);
  await context.route("**/*", async (route) => {
    const r = route.request(),
      u = new URL(r.url());
    if (u.origin !== origin) {
      external.push(u.origin);
      return route.abort();
    }
    requests.push({ path: u.pathname, method: r.method() });
    if (r.method() !== "GET")
      return route.fulfill({ status: 403, body: "Forbidden" });
    if (u.pathname.startsWith("/api/")) {
      const loggedIn = (await r.allHeaders())["cookie"]?.includes(
        "session_fixture=synthetic-cookie",
      );
      if (!loggedIn)
        return route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "unauthorized", message: "session required" },
            trace_id: tid,
          }),
        });
      let body: unknown = { items: [], next_cursor: null };
      if (u.pathname === "/api/v1/me") body = identity;
      if (u.pathname === "/api/v1/ui/bootstrap") body = bootstrap();
      if (u.pathname === "/api/v1/capabilities") body = { items: capabilities };
      if (u.pathname === "/api/v1/work-items")
        body = {
          items: [
            {
              id: wid,
              title: "受保护的会话记录",
              kind: "task",
              status: "open",
              created_at: now(),
              created_by: identity.id,
            },
          ],
          next_cursor: null,
        };
      if (u.pathname === `/api/v1/tasks/${tid}`)
        body = {
          id: tid,
          work_item_id: wid,
          capability: "local.simulate",
          resource_id: "local-ledger",
          generation: 0,
          state: "WAITING_APPROVAL",
          created_at: now(),
          updated_at: now(),
          trace_id: tid,
        };
      if (u.pathname === "/api/v1/approvals")
        body = {
          items: [
            {
              id: wid,
              task_id: tid,
              state: "PENDING",
              risk: "MEDIUM",
              created_at: now(),
              expires_at: new Date(Date.now() + 600000).toISOString(),
              resource_id: "local-ledger",
              scope: "synthetic only",
            },
          ],
          next_cursor: null,
        };
      if (u.pathname.endsWith("/attempts"))
        body = { items: [], source_meta: meta() };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    }
    const relative = u.pathname.slice("/app/".length);
    let file = resolve(root, relative || "index.html");
    if (!file.startsWith(root + "/")) return route.abort();
    if (!existsSync(file) || !statSync(file).isFile())
      file = resolve(root, "index.html");
    return route.fulfill({
      status: 200,
      contentType:
        (
          {
            ".html": "text/html",
            ".js": "text/javascript",
            ".css": "text/css",
            ".json": "application/json",
          } as Record<string, string>
        )[extname(file)] ?? "application/octet-stream",
      body: readFileSync(file),
    });
  });
  return { requests, external };
}
test("session build refuses an anonymous visitor without minting a local actor", async ({
  page,
  context,
}) => {
  const h = await host(context, false);
  await page.goto(origin + "/app/");
  await expect(
    page.getByRole("heading", { name: "401", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "返回登录" })).toHaveAttribute(
    "href",
    "/",
  );
  expect(
    h.requests.some((r) => r.method !== "GET" || r.path === "/local/session"),
  ).toBe(false);
  expect(h.requests.some((r) => r.path === "/api/v1/ui/bootstrap")).toBe(false);
  expect(h.external).toEqual([]);
});
test("HTTPS session cookie loads the workspace read-only, and expired identity hides records", async ({
  page,
  context,
}) => {
  const h = await host(context, true);
  await page.goto(origin + "/app/");
  await expect(page.getByLabel("你想完成的事")).toBeVisible();
  await expect(page.locator(".ws-runtime")).toContainText("只读发布");
  await page.getByLabel("你想完成的事").fill("只读发布不能发起");
  await expect(page.getByRole("button", { name: "检查并发起" })).toBeDisabled();
  await page.goto(origin + `/app/workbench/tasks/${tid}`);
  await expect(
    page.getByRole("heading", { name: "受保护的会话记录", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "允许这次操作", exact: true }),
  ).toBeDisabled();
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "session_fixture",
  );
  expect(
    await page.evaluate(() =>
      navigator.serviceWorker.getRegistrations().then((r) => r.length),
    ),
  ).toBe(0);
  await context.clearCookies();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "401", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "受保护的会话记录", exact: true }),
  ).toHaveCount(0);
  expect(
    h.requests.some((r) => r.method !== "GET" || r.path === "/local/session"),
  ).toBe(false);
  expect(h.external).toEqual([]);
});
