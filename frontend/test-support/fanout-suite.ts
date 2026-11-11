import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";
async function start(page: Page, gated = false) {
  await page.goto("/workbench/fanout");
  await expect(
    page.getByRole("heading", { name: "一次交办，多处协同。" }),
  ).toBeVisible();
  await expect(page.locator(".fo-recipes button")).toHaveCount(4);
  await page
    .getByLabel("多平台工作意图")
    .fill("Local offline paper summary and experiment");
  if (gated) await page.getByLabel(/Colab \/ Mac 算力/).check();
  await page.getByRole("button", { name: "一键发起协同流水线" }).click();
  await expect(page).toHaveURL(/\/workbench\/fanout\/[a-f0-9-]+/);
  await expect(page.getByLabel("协同流水线详情")).toBeVisible();
}
async function advance(page: Page, count = 1) {
  for (let i = 0; i < count; i++) {
    const response = page.waitForResponse(
      (r) => r.url().endsWith("/simulate") && r.request().method() === "POST",
    );
    await page
      .getByRole("button", { name: "推进本地模拟", exact: true })
      .click();
    expect((await response).status()).toBe(200);
    await expect(
      page.getByRole("button", { name: "推进本地模拟", exact: true }),
    ).toBeEnabled();
  }
}
export function fanoutSuite(live: boolean) {
  test("V3 aggregate approval, per-branch receipts and convergence", async ({
    page,
  }) => {
    await start(page, true);
    await expect(page.locator(".fo-branch")).toHaveCount(5);
    await advance(page);
    await expect(
      page.locator('.fo-branch[data-state="SUCCEEDED"]'),
    ).toHaveCount(2);
    await expect(
      page.locator('.fo-branch[data-state="WAITING_APPROVAL"]'),
    ).toHaveCount(1);
    await page
      .getByRole("button", { name: "允许这次操作", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "允许这次操作", exact: true }),
    ).not.toBeVisible();
    await advance(page, 4);
    await expect(
      page.locator('.fo-branch[data-state="SUCCEEDED"]'),
    ).toHaveCount(5);
    await expect(page.locator(".fo-receipt")).toHaveCount(5);
    await page
      .getByRole("button", { name: "Outbox 队列", exact: true })
      .click();
    await expect(
      page.getByText("尝试 1 · 代数 1", { exact: false }),
    ).toHaveCount(5);
    const dir = `evidence/workspace`;
    mkdirSync(dir, { recursive: true });
    await page.screenshot({
      path: `${dir}/v3-${live ? "loopback" : "mock"}-fanout.png`,
      fullPage: true,
    });
  });
  test("V3 rejection closes only gated branch, offline disables writes and reconnects", async ({
    page,
    context,
  }) => {
    await start(page, true);
    await page.getByRole("button", { name: "拒绝中风险分支" }).click();
    await expect(page.locator('.fo-branch[data-state="CANCELED"]')).toHaveCount(
      1,
    );
    await advance(page, 3);
    await expect(
      page.locator('.fo-branch[data-state="SUCCEEDED"]'),
    ).toHaveCount(4);
    await context.setOffline(true);
    await expect(
      page.getByRole("button", { name: "推进本地模拟", exact: true }),
    ).toBeDisabled();
    await context.setOffline(false);
    await expect(
      page.getByRole("button", { name: "推进本地模拟", exact: true }),
    ).toBeEnabled();
    await page.getByRole("button", { name: "快捷指令", exact: true }).click();
    await expect(page.locator(".fo-command")).toContainText(
      "--idempotency-key",
    );
    expect(await page.locator(".fo-command").textContent()).not.toContain(
      "github_pat_",
    );
  });
  test("V3 one failure retries independently while successful sibling stays closed", async ({
    page,
  }) => {
    await start(page);
    await advance(page);
    await page.getByLabel("故障分支").selectOption("notion");
    await page.getByRole("button", { name: "模拟可重试失败" }).click();
    const notion = page.locator(".fo-branch").filter({
      has: page.getByRole("heading", { name: "Notion", exact: true }),
    });
    await expect(notion).toContainText("simulated_transient_failure");
    await advance(page);
    await expect(
      page.locator('.fo-branch[data-state="SUCCEEDED"]'),
    ).toHaveCount(3);
    await expect
      .poll(async () => {
        await advance(page);
        return page.locator('.fo-branch[data-state="SUCCEEDED"]').count();
      })
      .toBe(4);
    await page
      .getByRole("button", { name: "Outbox 队列", exact: true })
      .click();
    await expect(notion).toContainText("尝试 2 · 代数 2");
    await expect(
      page.getByText("尝试 1 · 代数 1", { exact: false }),
    ).toHaveCount(3);
  });
  for (const width of [1600, 1280, 768, 390]) {
    test(`V3 accessible recipe console at ${width}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto("/workbench/fanout");
      await expect(page.locator(".fo-recipes button")).toHaveCount(4);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.getByLabel("多平台工作意图").focus();
      await expect(page.getByLabel("多平台工作意图")).toBeFocused();
      const results = await new AxeBuilder({ page })
        .include(".fo-composer")
        .include(".fo-recipes")
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(results.violations).toEqual([]);
      await page.screenshot({
        path: `evidence/workspace/v3-${live ? "loopback" : "mock"}-${width}.png`,
        fullPage: true,
      });
    });
  }
}
