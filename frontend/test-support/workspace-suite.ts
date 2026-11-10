import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
async function home(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "交给工作坊",
  );
  await page.getByLabel("你想完成的事").fill("新的本地工作");
  await expect(page.getByRole("button", { name: "检查并发起" })).toBeEnabled();
}
async function create(page: Page, title: string, outcome = "SUCCEEDED") {
  await home(page);
  await page.getByLabel("你想完成的事").fill(title);
  await page.getByRole("button", { name: "检查并发起" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "确认发起", exact: true }),
  ).toBeDisabled();
  if (outcome !== "SUCCEEDED") {
    await dialog.getByText("演示选项", { exact: true }).click();
    await dialog.getByLabel("前台模拟结果").selectOption(outcome);
  }
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "确认发起", exact: true }).click();
  await expect(page).toHaveURL(/\/workbench\/tasks\/[a-f0-9-]+/);
  await expect(page.locator(".ws-page-title .ws-status")).toHaveAttribute(
    "data-state",
    "WAITING_APPROVAL",
  );
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toBeVisible();
  return new URL(page.url()).pathname.split("/").at(-1)!;
}
async function decide(page: Page, reject = false) {
  await page
    .getByRole("button", {
      name: reject ? "拒绝" : "允许这次操作",
      exact: true,
    })
    .click();
  await expect(page.getByRole("dialog")).toContainText("local-ledger");
  await page
    .getByRole("button", {
      name: reject ? "确认拒绝" : "确认允许",
      exact: true,
    })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
}
export function workspaceSuite(live: boolean) {
  test("V2 conversation, sync and verified upload/download remain interactive", async ({
    page,
  }) => {
    await home(page);
    await page.getByRole("button", { name: "同步当前草稿到多端" }).click();
    await expect(page.getByText(/同步游标：sync-cursor-[1-9]/)).toBeVisible();
    await page.getByRole("button", { name: "上传验证附件（SHA-256）" }).click();
    await expect(page.getByText(/已登记附件：/)).toBeVisible();
    await page.getByRole("link", { name: "结果库", exact: true }).click();
    const download = page.waitForEvent("download");
    await page
      .locator(".ws-artifact")
      .filter({ hasText: "workspace-note.md" })
      .getByRole("button", { name: "受控下载" })
      .last()
      .click();
    const file = await download;
    expect(file.suggestedFilename()).toBe("workspace-note.md");
    expect(await file.failure()).toBeNull();
    await expect(page.getByText(/SHA-256 已核验/)).toBeVisible();
    await page.getByRole("link", { name: "助手", exact: true }).click();
    await page.getByLabel("发起新对话标题").fill("V2 会话浏览器回归");
    await page.getByRole("button", { name: "发送并记录会话" }).click();
    await expect(
      page
        .locator(".ws-saved")
        .getByRole("heading", { name: "V2 会话浏览器回归" }),
    ).toBeVisible();
    await expect(
      page.locator(".ws-saved").getByText(/消息数：1/),
    ).toBeVisible();
  });
  for (const width of [1600, 1280, 768, 390])
    test(`user workspace pages, navigation and detail at ${width}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 1000 });
      const external: string[] = [];
      page.on("request", (r) => {
        if (!["127.0.0.1", "localhost"].includes(new URL(r.url()).hostname))
          external.push(r.url());
      });
      await home(page);
      await page.screenshot({
        path: `evidence/workspace/${live ? "loopback" : "mock"}-home-${width}.png`,
        fullPage: true,
      });
      for (const [path, title] of [
        ["/workbench/history", "我的工作"],
        ["/workbench/results", "结果库"],
        ["/workbench/assistants", "认识工作坊的助手"],
      ]) {
        await page.goto(path);
        await expect(
          page.getByRole("heading", { name: title, exact: true }),
        ).toBeVisible();
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
      }
      const tid = await create(page, `前台尺寸验证 ${width}`);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: `evidence/workspace/${live ? "loopback" : "mock"}-detail-${width}.png`,
        fullPage: true,
      });
      if (live) {
        await page.reload();
        await expect(page.locator(".ws-page-title .ws-status")).toHaveAttribute(
          "data-state",
          "WAITING_APPROVAL",
        );
      }
      await decide(page, true);
      await expect(page.locator(".ws-page-title .ws-status")).toHaveAttribute(
        "data-state",
        "CANCELED",
      );
      await page.getByRole("link", { name: "返回我的工作" }).click();
      await page.getByLabel("搜索我的工作").fill(tid);
      await expect(page.locator(".ws-task-card")).toHaveCount(1);
      expect(external).toEqual([]);
    });
  test("user request approval result history and export form one local workflow", async ({
    page,
  }) => {
    const tid = await create(page, "前台完整闭环");
    await decide(page);
    await expect(page.locator(".ws-page-title .ws-status")).toHaveAttribute(
      "data-state",
      "SUCCEEDED",
      { timeout: 15000 },
    );
    await expect(
      page.getByRole("heading", { name: "产物登记", exact: true }),
    ).toBeVisible();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "导出任务记录" }).click(),
    ]);
    const path = await download.path();
    expect(path).toBeTruthy();
    const record = JSON.parse(readFileSync(path!, "utf8"));
    expect(record.task.id).toBe(tid);
    expect(record.task.state).toBe("SUCCEEDED");
    expect(record.artifacts.length).toBeGreaterThan(0);
    expect(record.events.length).toBeGreaterThan(0);
    expect(record).not.toHaveProperty("session");
    await page.getByRole("link", { name: "结果库", exact: true }).click();
    await page.getByLabel("搜索结果").fill("前台完整闭环");
    await expect(page.locator(".ws-results>section")).toHaveCount(1);
    await page.getByRole("link", { name: "查看来源任务" }).click();
    await expect(page).toHaveURL(new RegExp(`/workbench/tasks/${tid}$`));
    await page.getByRole("link", { name: "管理后台", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "总控制台", exact: true }),
    ).toBeVisible();
    await page.getByRole("link", { name: "用户工作坊", exact: true }).click();
    await expect(page.getByLabel("你想完成的事")).toBeVisible();
  });
  test("ideas and research notes save without starting execution", async ({
    page,
  }) => {
    const taskPosts: string[] = [];
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        new URL(r.url()).pathname === "/api/v1/tasks"
      )
        taskPosts.push(r.url());
    });
    for (const [kind, title] of [
      ["想法", "一份不会自动执行的想法"],
      ["研究笔记", "一份不会调用模型的研究记录"],
    ]) {
      await home(page);
      await page.getByRole("button", { name: kind, exact: true }).click();
      await page.getByLabel("你想完成的事").fill(title);
      await page.getByRole("button", { name: "保存到我的工作" }).click();
      await page.getByRole("dialog").getByRole("checkbox").check();
      await page.getByRole("button", { name: "确认保存", exact: true }).click();
      await expect(page).toHaveURL(/\/workbench\/history$/);
      await expect(
        page.getByRole("heading", { name: title, exact: true }),
      ).toBeVisible();
    }
    expect(taskPosts).toEqual([]);
  });
  test("failed and lost-lease tasks stay honest and never create a success result", async ({
    page,
  }) => {
    test.setTimeout(80000);
    for (const outcome of ["FAILED", "NEEDS_RECONCILIATION"]) {
      await create(page, `前台异常 ${outcome}`, outcome);
      await decide(page);
      await expect(page.locator(".ws-page-title .ws-status")).toHaveAttribute(
        "data-state",
        outcome,
        { timeout: 30000 },
      );
      await expect(page.locator(".ws-task-summary")).toContainText(
        outcome === "FAILED" ? "没有完成" : "不会自动重排",
      );
      await expect(page.locator(".ws-artifact")).toHaveCount(0);
    }
  });
  test("session draft survives reload and offline task data stays read-only", async ({
    page,
    context,
  }) => {
    await home(page);
    await page.getByLabel("你想完成的事").fill("当前会话内保留的草稿");
    await page.reload();
    await expect(page.getByLabel("你想完成的事")).toHaveValue(
      "当前会话内保留的草稿",
    );
    await create(page, "断线时不得授权");
    await context.setOffline(true);
    await expect(page.locator(".ws-runtime")).toContainText("缓存只读");
    await expect(
      page.getByRole("button", { name: "允许这次操作", exact: true }),
    ).toBeDisabled();
    await context.setOffline(false);
    await page.getByRole("button", { name: "刷新状态", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "允许这次操作", exact: true }),
    ).toBeEnabled();
    await decide(page, true);
  });
  test("front workspace home and task pass basic accessibility and reduced motion", async ({
    page,
  }) => {
    const { default: AxeBuilder } = await import("@axe-core/playwright");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await home(page);
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    await create(page, "可访问性任务");
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    await decide(page, true);
  });
  if (live) {
    test("task acknowledgement loss retries with the original payload and creates exactly one task", async ({
      page,
    }) => {
      let intercepted = false;
      const keys: string[] = [],
        workPosts: string[] = [];
      page.on("request", (r) => {
        if (
          r.method() === "POST" &&
          new URL(r.url()).pathname === "/api/v1/work-items"
        )
          workPosts.push(r.url());
      });
      await page.route("**/api/v1/tasks", async (route) => {
        if (route.request().method() !== "POST") return route.continue();
        keys.push(route.request().headers()["idempotency-key"]);
        if (!intercepted) {
          intercepted = true;
          const r = await route.fetch();
          expect(r.status()).toBe(202);
          await route.abort("failed");
        } else await route.continue();
      });
      await home(page);
      await page.getByLabel("你想完成的事").fill("丢失回执也只创建一次");
      await page.getByRole("button", { name: "检查并发起" }).click();
      await page.getByRole("dialog").getByRole("checkbox").check();
      await page.getByRole("button", { name: "确认发起", exact: true }).click();
      await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
      await page
        .getByRole("dialog")
        .getByRole("button", { name: "返回", exact: true })
        .click();
      await page.getByRole("button", { name: "重新检查", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "继续这份提交" }),
      ).toBeEnabled();
      await page.reload();
      await expect(
        page.getByRole("button", { name: "继续这份提交" }),
      ).toBeEnabled();
      await page.getByRole("button", { name: "继续这份提交" }).click();
      await page.getByRole("dialog").getByRole("checkbox").check();
      await page.getByRole("button", { name: "确认发起", exact: true }).click();
      await expect(page).toHaveURL(/\/workbench\/tasks\/[a-f0-9-]+/);
      expect(workPosts).toHaveLength(1);
      expect(keys).toHaveLength(2);
      expect(keys[0]).toBeTruthy();
      expect(keys[0]).toBe(keys[1]);
      const t = await page.request.get("/api/v1/tasks").then((r) => r.json());
      const id = new URL(page.url()).pathname.split("/").at(-1);
      const saved = t.items.find((v: { id: string }) => v.id === id);
      expect(
        t.items.filter(
          (v: { work_item_id: string }) =>
            v.work_item_id === saved.work_item_id,
        ),
      ).toHaveLength(1);
      await decide(page, true);
    });
    test("expired approval and unauthorized refresh cannot expose stale private records", async ({
      page,
    }) => {
      const tid = await create(page, "身份失效后必须隐藏的标题");
      await page.route("**/api/v1/approvals", async (route) => {
        const r = await route.fetch();
        const json = await r.json();
        json.items = json.items.map((a: SchemaApproval) =>
          a.task_id === tid ? { ...a, expires_at: "2000-01-01T00:00:00Z" } : a,
        );
        await route.fulfill({ response: r, json });
      });
      await page.getByRole("button", { name: "刷新状态", exact: true }).click();
      await expect(
        page.getByRole("button", { name: "允许这次操作", exact: true }),
      ).toBeDisabled();
      await expect(page.locator(".ws-approval")).toContainText("已过有效期");
      await page.route(`**/api/v1/tasks/${tid}`, (route) =>
        route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "unauthorized", message: "test identity expired" },
            trace_id: crypto.randomUUID(),
          }),
        }),
      );
      await page.getByRole("button", { name: "刷新状态", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: "401", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("heading", {
          name: "身份失效后必须隐藏的标题",
          exact: true,
        }),
      ).toHaveCount(0);
      await expect(page.locator(".ws-approval")).toHaveCount(0);
      await page.unrouteAll({ behavior: "wait" });
    });
  }
}
type SchemaApproval = { task_id: string; expires_at: string };
