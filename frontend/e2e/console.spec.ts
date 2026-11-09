import { writeFileSync } from "node:fs";
import { test, expect, type Page } from "@playwright/test";
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
async function ready(page: Page, path = "/architecture") {
  await page.goto(path);
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.waitForTimeout(200);
}
async function create(page: Page) {
  await ready(page, "/tasks");
  await page.getByRole("button", { name: "新建模拟任务" }).click();
  await page.getByRole("button", { name: "确认 · LOCAL MOCK" }).click();
  await expect(page).toHaveURL(/\/tasks\/[a-f0-9-]+/);
  await expect(
    page.getByText("WAITING_APPROVAL", { exact: true }).first(),
  ).toBeVisible();
}
for (const width of [1600, 1280, 768, 390])
  test(`all page templates and interactions at ${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    const remote: string[] = [];
    page.on("request", (req) => {
      if (!["127.0.0.1", "localhost"].includes(new URL(req.url()).hostname))
        remote.push(req.url());
    });
    await ready(page);
    await page.getByRole("button", { name: "主控故障", exact: true }).click();
    await expect(page.getByText("模拟 OFFLINE · 写入暂停")).toBeVisible();
    await page.getByRole("button", { name: "恢复对账", exact: true }).click();
    await page.screenshot({
      path: `evidence/screenshots/home-${width}.png`,
      fullPage: true,
    });
    for (const route of routes) {
      await ready(page, `/${route}`);
      const search = page.getByRole("textbox", { name: "搜索记录" });
      if (await search.count()) {
        await search.fill("non-matching-query");
        await expect(
          page.getByRole("heading", { name: "EMPTY", exact: true }),
        ).toBeVisible();
        await search.fill("");
        await page.getByRole("button", { name: "名称排序" }).click();
      }
      await page.screenshot({
        path: `evidence/screenshots/${route}-${width}.png`,
        fullPage: true,
      });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        route,
      ).toBe(true);
    }
    for (const [kind, id] of [
      ["nodes", "us"],
      ["services", "service-us"],
      ["agents", "agent-1"],
    ]) {
      await ready(page, `/${kind}/${id}`);
      for (const tab of await page.getByRole("tab").all()) {
        await tab.click();
        await expect(tab).toHaveAttribute("aria-selected", "true");
      }
      await page.screenshot({
        path: `evidence/screenshots/detail-${kind}-${width}.png`,
        fullPage: true,
      });
    }
    await create(page);
    await page.getByRole("tab", { name: "Events", exact: true }).click();
    await expect(page.getByText("LOCAL MOCK · WAITING_APPROVAL")).toBeVisible();
    await page.screenshot({
      path: `evidence/screenshots/detail-tasks-${width}.png`,
      fullPage: true,
    });
    for (const version of ["v1.0", "v2.0-prism"]) {
      await page.goto(`/versions/${version}/`);
      await expect(page.locator("body")).not.toBeEmpty();
      await page.screenshot({
        path: `evidence/screenshots/${version}-${width}.png`,
        fullPage: true,
      });
    }
    expect(remote).toEqual([]);
  });
test("full local task approval worker attempts events artifacts flow", async ({
  page,
}) => {
  const exchanges: { method: string; path: string; status: number }[] = [];
  page.on("response", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/"))
      exchanges.push({
        method: r.request().method(),
        path: new URL(r.url()).pathname,
        status: r.status(),
      });
  });
  await create(page);
  const taskUrl = page.url();
  await page.getByRole("link", { name: "前往本地模拟审批" }).click();
  await page.getByRole("button", { name: "演示批准" }).first().click();
  await expect(page.getByRole("dialog")).toContainText("local-ledger");
  await page.getByRole("button", { name: "确认 · LOCAL MOCK" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("link", { name: "查看关联任务" }).first().click();
  expect(page.url()).toBe(taskUrl);
  await expect(
    page.getByText("SUCCEEDED", { exact: true }).first(),
  ).toBeVisible({ timeout: 12000 });
  for (const tab of ["Attempts", "Events", "Approvals", "Artifacts"]) {
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(page.locator(".detail-body")).not.toContainText("暂无可靠");
  }
  await page.getByRole("tab", { name: "Events", exact: true }).click();
  await expect(page.getByText("LOCAL MOCK · RUNNING")).toBeVisible();
  await page.screenshot({
    path: "evidence/screenshots/task-success.png",
    fullPage: true,
  });
  writeFileSync(
    "evidence/loopback-exchanges.json",
    JSON.stringify(
      { mode: "MSW_SYNTHETIC_NOT_GLM_INTEGRATION", exchanges },
      null,
      2,
    ),
  );
});
test("errors, cached offline, stale, empty, loading, detail 404, keyboard, reduced motion", async ({
  page,
}) => {
  await ready(page, "/nodes");
  if (!(await page.getByLabel("模拟响应").isVisible()))
    await page.locator("footer summary").click();
  for (const code of ["401", "403", "404", "409", "503"]) {
    await page.getByLabel("模拟响应").selectOption(code);
    await expect(
      page.getByRole("heading", { name: code, exact: true }),
    ).toBeVisible();
  }
  await page.getByLabel("模拟响应").selectOption("offline");
  await expect(
    page.getByRole("heading", { name: "OFFLINE", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".connection-banner")).toContainText(
    "不会提升 Mac",
  );
  await page.getByLabel("模拟响应").selectOption("stale");
  await expect(page.getByText("STALE", { exact: true }).first()).toBeVisible();
  await page.getByLabel("模拟响应").selectOption("normal");
  await page.goto("/nodes/missing");
  await expect(
    page.getByRole("heading", { name: "404", exact: true }),
  ).toBeVisible();
  await ready(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(
    await page
      .locator(".packet")
      .evaluate((el) => getComputedStyle(el).display),
  ).toBe("none");
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toBeVisible();
  await page.screenshot({
    path: "evidence/screenshots/reduced-motion.png",
    fullPage: true,
  });
});
test("cancel, failure, reconciliation and permissions remain local", async ({
  page,
}) => {
  await create(page);
  await page.getByRole("button", { name: "取消模拟任务" }).click();
  await page.getByRole("button", { name: "确认 · LOCAL MOCK" }).click();
  await expect(page.locator(".header-actions .badge")).toHaveText(/CANCELED/);
  for (const outcome of ["FAILED", "NEEDS_RECONCILIATION"]) {
    await page.getByRole("link", { name: "返回任务工作台" }).click();
    if (!(await page.getByLabel("模拟响应").isVisible()))
      await page.locator("footer summary").click();
    await page.getByLabel("模拟 Worker 结果").selectOption(outcome);
    await page.getByRole("button", { name: "新建模拟任务" }).click();
    await page.getByRole("button", { name: "确认 · LOCAL MOCK" }).click();
    await expect(page).toHaveURL(/\/tasks\/[a-f0-9-]+/);
    const currentTask = page.url();
    await page.getByRole("link", { name: "前往本地模拟审批" }).click();
    await page.getByRole("button", { name: "演示批准" }).first().click();
    await page.getByRole("button", { name: "确认 · LOCAL MOCK" }).click();
    await expect(page.getByRole("dialog")).not.toBeVisible();
    await page
      .locator(`a[href="${new URL(currentTask).pathname}"]`)
      .first()
      .click();
    await expect(page.locator(".header-actions .badge")).toHaveText(outcome, {
      timeout: 10000,
    });
    await page.getByRole("tab", { name: "Artifacts", exact: true }).click();
    await expect(page.locator(".detail-body")).toContainText("暂无可靠");
  }
  if (!(await page.getByLabel("模拟响应").isVisible()))
    await page.locator("footer summary").click();
  await page.getByLabel("模拟响应").selectOption("403");
  await expect(
    page.getByRole("heading", { name: "403", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".detail-body")).toHaveCount(0);
});
test("basic WCAG checks on home, mobile catalog and modal", async ({
  page,
}) => {
  const { default: AxeBuilder } = await import("@axe-core/playwright");
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/", "/architecture", "/agents", "/tasks"]) {
    await ready(page, path);
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
  }
  await page.getByRole("button", { name: "新建模拟任务" }).click();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
});
