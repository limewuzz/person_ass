import { test, expect } from "@playwright/test";
test("/app build has a working entry, direct routes, reloads and historical links", async ({
  page,
  request,
  browser,
}) => {
  const privateContext = await browser.newContext();
  for (const path of ["me", "tasks", "nodes", "audit", "events"]) {
    const r = await privateContext.request.get(
      `http://127.0.0.1:5174/api/v1/${path}`,
    );
    expect(r.status()).toBe(401);
    expect(r.headers()["cache-control"]).toBe("no-store");
  }
  await privateContext.close();
  expect((await request.get("/app", { maxRedirects: 0 })).status()).toBe(308);
  expect((await request.get("/workbench/history")).status()).toBe(404);
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  await page.goto("/app/");
  await expect(page.getByLabel("你想完成的事")).toBeVisible();
  const paths = [
    "architecture",
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
    "workbench/history",
    "workbench/results",
    "workbench/assistants",
    "nodes/us-server",
    "services/svc.mwcp.portal",
    "agents/agent.rakazo.chief",
  ];
  for (const path of paths) {
    const r = await page.goto(`/app/${path}`);
    expect(r!.status()).toBe(200);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("没有这个页面。", { exact: true })).toHaveCount(
      0,
    );
  }
  await page.goto("/app/architecture");
  await expect(page.getByRole("link", { name: "V1.0 历史" })).toHaveAttribute(
    "href",
    "/app/versions/v1.0/",
  );
  for (const version of ["v1.0", "v2.0-prism"]) {
    const r = await page.goto(`/app/versions/${version}/`);
    expect(r!.status()).toBe(200);
    await expect(page.locator("body")).not.toBeEmpty();
  }
  for (const width of [1600, 1280, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("/app/");
    await expect(page.getByLabel("你想完成的事")).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("你想完成的事")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `evidence/prefix/workspace-${width}.png`,
      fullPage: true,
    });
  }
  const r = await request.get("/app/assets/does-not-exist.js");
  expect(r.status()).toBe(404);
  expect(
    (
      await request.get("/app/", {
        headers: { Host: "control.example.invalid" },
      })
    ).status(),
  ).toBe(403);
  const html = await request.get("/app/");
  expect(html.headers()["x-frame-options"]).toBe("DENY");
  expect(html.headers()["content-security-policy"]).toContain(
    "frame-ancestors 'none'",
  );
  expect(failures).toEqual([]);
});
