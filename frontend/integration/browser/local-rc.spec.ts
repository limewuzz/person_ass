import { test, expect, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
const folder = "evidence/live-integration";
mkdirSync(`${folder}/screenshots`, { recursive: true });
const routes = [
  "dashboard",
  "tasks",
  "approvals",
  "nodes",
  "services",
  "observability",
  "agents",
  "workflows",
  "network",
  "models",
  "projects",
  "integrations",
  "compute",
  "artifacts",
  "knowledge",
];
async function ready(page: Page, path: string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(250);
}
async function create(page: Page, outcome = "SUCCEEDED") {
  await ready(page, "/tasks");
  await page.getByRole("button", { name: "新建模拟任务" }).click();
  await page.getByLabel("模拟任务结果").selectOption(outcome);
  await page.getByRole("button", { name: "确认 · LOCAL MOCK" }).click();
  await expect(page).toHaveURL(/\/tasks\/[a-f0-9-]+/);
  const tid = new URL(page.url()).pathname.split("/").at(-1)!;
  await expect(page.locator(".header-actions .badge")).toHaveText(
    "WAITING_APPROVAL",
  );
  return tid;
}
async function approve(page: Page, tid: string) {
  await page.getByRole("link", { name: "前往本地模拟审批" }).click();
  await page.getByRole("textbox", { name: "搜索记录" }).fill(tid);
  await page.getByRole("button", { name: "演示批准", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("local-ledger");
  await expect(page.getByRole("dialog")).toContainText("arguments_summary");
  await expect(
    page.getByRole("button", { name: "确认 · LOCAL MOCK" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "确认 · LOCAL MOCK" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.locator(`a[href="/tasks/${tid}"]`).first().click();
}
for (const width of [1600, 1280, 768, 390])
  test(`all 22 templates with actual new API at ${width}`, async ({ page }) => {
    const errors: string[] = [],
      external: string[] = [],
      bad: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => {
      if (new URL(r.url()).hostname !== "127.0.0.1") external.push(r.url());
    });
    page.on("response", (r) => {
      if (r.url().includes("/api/") && r.status() >= 500)
        bad.push(new URL(r.url()).pathname);
    });
    await page.setViewportSize({ width, height: 1000 });
    const tid = await create(page);
    for (const path of [
      "/architecture",
      ...routes.map((r) => `/${r}`),
      "/nodes/us-server",
      "/services/svc.mwcp.portal",
      "/agents/agent.rakazo.chief",
      `/tasks/${tid}`,
    ]) {
      await ready(page, path);
      await expect(page.locator(".connection-banner")).toContainText(
        "GLM LOOPBACK",
      );
      await expect(
        page.getByRole("heading", { name: "503", exact: true }),
      ).toHaveCount(0);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        path,
      ).toBe(true);
      const search = page.getByRole("textbox", { name: "搜索记录" });
      if (await search.count()) {
        await search.fill("no-matching-synthetic-string");
        await expect(
          page.getByRole("heading", { name: "EMPTY", exact: true }),
        ).toBeVisible();
        await search.fill("");
      }
      const tabs = page.getByRole("tab");
      for (const tab of await tabs.all()) {
        await tab.click();
        await expect(tab).toHaveAttribute("aria-selected", "true");
      }
      await page.screenshot({
        path: `${folder}/screenshots/${path.replaceAll("/", "_") || "home"}-${width}.png`,
        fullPage: true,
      });
    }
    await page.getByRole("button", { name: "取消模拟任务" }).click();
    await page.getByRole("button", { name: "确认 · LOCAL MOCK" }).click();
    await expect(page.locator(".header-actions .badge")).toHaveText("CANCELED");
    for (const version of ["v1.0", "v2.0-prism"]) {
      await page.goto(`/versions/${version}/`);
      await expect(page.locator("body")).not.toBeEmpty();
      await page.screenshot({
        path: `${folder}/screenshots/${version}-${width}.png`,
        fullPage: true,
      });
    }
    expect(
      await page.evaluate(() =>
        navigator.serviceWorker.getRegistrations().then((r) => r.length),
      ),
    ).toBe(0);
    expect(errors).toEqual([]);
    expect(external).toEqual([]);
    expect(bad).toEqual([]);
  });

test("real loopback task approval worker trace artifacts, readiness and session boundaries", async ({
  page,
}) => {
  const exchanges: { method: string; path: string; status: number }[] = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/"))
      exchanges.push({
        method: r.request().method(),
        path: new URL(r.url()).pathname,
        status: r.status(),
      });
  });
  const tid = await create(page);
  await approve(page, tid);
  await expect(page.locator(".header-actions .badge")).toHaveText("SUCCEEDED", {
    timeout: 15000,
  });
  const trace = await page
    .getByText("trace_id", { exact: true })
    .locator("..")
    .locator("dd")
    .textContent();
  expect(trace).toMatch(/^[a-f0-9-]{36}$/);
  await page.getByRole("tab", { name: "Overview", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "Attempts", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(
    page.getByRole("tab", { name: "Overview", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  for (const tab of ["Attempts", "Events", "Approvals", "Artifacts"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(page.locator(".detail-body .state-panel")).toHaveCount(0);
    if (tab === "Approvals")
      await expect(page.locator(".detail-body")).toContainText("CONSUMED");
    if (tab === "Artifacts")
      await expect(page.locator(".detail-body")).toContainText(
        "LOCAL_MEMORY_MOCK",
      );
  }
  await page.screenshot({
    path: `${folder}/screenshots/real-task-success.png`,
    fullPage: true,
  });
  const security = await page.evaluate(async () => {
    const session = await fetch("/local/session", { method: "POST" }).then(
      (r) => r.json(),
    );
    const noCsrf = await fetch("/api/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const worker = await fetch("/api/v1/workers/forged/claim", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-MW-CSRF": session.csrf,
      },
      body: "{}",
    });
    const ready = await fetch("/api/v1/health/ready");
    return {
      noCsrf: noCsrf.status,
      worker: worker.status,
      ready: ready.status,
      body: await ready.json(),
      cookies: document.cookie,
      localStorage: localStorage.length,
    };
  });
  expect(security.noCsrf).toBe(403);
  expect(security.worker).toBe(403);
  expect(security.ready).toBe(503);
  expect(security.body.dependency_status.database).toBe("not_connected");
  expect(security.cookies).not.toContain("mw_local_session");
  expect(security.localStorage).toBe(0);
  writeFileSync(
    `${folder}/http-exchanges.json`,
    JSON.stringify(
      {
        mode: "REAL_LOOPBACK_PROCESSES_WITH_SYNTHETIC_LEDGER",
        task_id: tid,
        trace_id: trace,
        exchanges,
        security: { ...security, cookies: undefined },
      },
      null,
      2,
    ),
  );
});

test("actual worker failure and lost lease reconcile without automatic requeue", async ({
  page,
}) => {
  test.setTimeout(60000);
  for (const outcome of ["FAILED", "NEEDS_RECONCILIATION"]) {
    const tid = await create(page, outcome);
    await approve(page, tid);
    await expect(page.locator(".header-actions .badge")).toHaveText(outcome, {
      timeout: 25000,
    });
    await page.getByRole("tab", { name: "Attempts", exact: true }).click();
    await expect(page.locator(".detail-body")).toContainText(outcome);
    await page.getByRole("tab", { name: "Artifacts", exact: true }).click();
    await expect(page.locator(".detail-body")).toContainText("暂无可靠");
    await page.screenshot({
      path: `${folder}/screenshots/${outcome}.png`,
      fullPage: true,
    });
  }
});

test("browser disconnect shows cached read-only and restores same writer", async ({
  page,
  context,
}) => {
  const tid = await create(page);
  await approve(page, tid);
  await expect(page.locator(".header-actions .badge")).toHaveText("SUCCEEDED", {
    timeout: 15000,
  });
  await context.setOffline(true);
  await expect(page.locator(".connection-banner")).toContainText("缓存只读", {
    timeout: 12000,
  });
  await page.getByRole("link", { name: "返回任务工作台" }).click();
  await expect(page.getByRole("button", { name: "新建模拟任务" })).toHaveCount(
    0,
  );
  await context.setOffline(false);
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByRole("button", { name: "新建模拟任务" })).toBeVisible({
    timeout: 10000,
  });
  await page.getByRole("textbox", { name: "搜索记录" }).fill(tid);
  await page.getByRole("link", { name: "查看", exact: true }).click();
  await expect(page.locator(".header-actions .badge")).toHaveText("SUCCEEDED");
  await page.screenshot({
    path: `${folder}/screenshots/reconnected-read-only-cache.png`,
    fullPage: true,
  });
});
