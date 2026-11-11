import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";
for (const width of [1600, 1280, 768, 390]) {
  test(`US portal is accessible and responsive at ${width}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const writes: string[] = [];
    page.on("request", (r) => {
      if (!["GET", "HEAD"].includes(r.method()))
        writes.push(new URL(r.url()).pathname);
    });
    await page.goto("/portal/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText(
      "想法很多",
    );
    await expect(page.locator(".scenario")).toHaveCount(4);
    await expect(page.locator(".tool")).toHaveCount(3);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const result = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(result.violations).toEqual([]);
    expect(writes).toEqual([]);
    mkdirSync("evidence/portal", { recursive: true });
    await page.screenshot({
      path: `evidence/portal/home-${width}.png`,
      fullPage: true,
    });
  });
}
test("portal hands off one private draft without starting any task", async ({
  page,
}) => {
  const mutations: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") mutations.push(new URL(r.url()).pathname);
  });
  await page.goto("/portal/");
  await page.getByRole("button", { name: "从方案开发开始" }).click();
  await expect(page.getByLabel("这次想推进的工作")).toBeFocused();
  await page
    .getByLabel("这次想推进的工作")
    .fill("private portal intent: turn this decision into development");
  await page.getByRole("button", { name: "到工作坊检查" }).click();
  await expect(page).toHaveURL(/\/workbench\/fanout\?recipe=decision$/);
  await expect(page.getByLabel("多平台工作意图")).toHaveValue(
    "private portal intent: turn this decision into development",
  );
  await expect(
    page.getByRole("button", { name: "方案定稿与开发排期", exact: false }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(page.url()).not.toContain("private");
  expect(mutations).toEqual([]);
  await expect(page.getByLabel("协同流水线列表").locator("button")).toHaveCount(
    0,
  );
});
test("portal search and legacy entry links stay navigable", async ({
  page,
}) => {
  await page.goto("/portal/");
  await page.getByRole("button", { name: "搜索入口" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("textbox").fill("额度");
  await expect(dialog.getByRole("link")).toHaveCount(1);
  await expect(dialog.getByRole("link")).toHaveAttribute("href", "/usage/");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  for (const href of ["/chat/", "/agent", "/models", "/usage/"])
    await expect(page.locator(`.tools a[href="${href}"]`)).toBeVisible();
});
test("blocked browser storage preserves the draft and never submits a task", async ({
  page,
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(window, "sessionStorage", {
      get() {
        throw new DOMException("blocked", "SecurityError");
      },
    }),
  );
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST") writes.push(new URL(r.url()).pathname);
  });
  await page.goto("/portal/");
  await page.getByLabel("这次想推进的工作").fill("keep this private draft");
  await page.getByRole("button", { name: "到工作坊检查" }).click();
  await expect(page.getByRole("alert")).toContainText("草稿未能保存");
  await expect(page.getByLabel("这次想推进的工作")).toHaveValue(
    "keep this private draft",
  );
  expect(writes).toEqual([]);
});
