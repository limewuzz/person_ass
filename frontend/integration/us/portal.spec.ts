import { test, expect, type BrowserContext } from "@playwright/test";
import { readFileSync, existsSync, statSync, mkdirSync } from "node:fs";
import { resolve, extname, sep } from "node:path";
import { bootstrap, identity } from "../../src/mocks/fixtures";
const origin = "https://magicworkshop.fun";
const root = resolve(process.env.MW_US_CANDIDATE_DIR ?? "MISSING_US_CANDIDATE");
const recipeConfig = JSON.parse(
  readFileSync(resolve("../backend/fanout/recipes.json"), "utf8"),
) as Record<
  string,
  { name: string; steps: [string, string, string, string[]][] }
>;
async function host(context: BrowserContext, authorized: boolean) {
  const requests: { path: string; method: string }[] = [],
    external: string[] = [];
  if (authorized)
    await context.addCookies([
      {
        name: "us_fixture_session",
        value: "synthetic-local-test",
        url: origin,
        httpOnly: true,
        secure: true,
        sameSite: "Strict",
      },
    ]);
  await context.route("**/*", async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    if (url.origin !== origin) {
      external.push(url.origin);
      return route.abort();
    }
    requests.push({ path: url.pathname, method: request.method() });
    if (request.method() !== "GET")
      return route.fulfill({
        status: 403,
        body: "No writes in static deployment candidate",
      });
    if (url.pathname.startsWith("/api/")) {
      if (
        !(await request.allHeaders()).cookie?.includes(
          "us_fixture_session=synthetic-local-test",
        )
      )
        return route.fulfill({
          status: 401,
          contentType: "application/json",
          body: JSON.stringify({
            error: { code: "unauthorized", message: "session required" },
            trace_id: identity.id,
          }),
        });
      let body: unknown = { items: [], next_cursor: null };
      if (url.pathname === "/api/v1/me") body = identity;
      if (url.pathname === "/api/v1/ui/bootstrap") body = bootstrap();
      if (url.pathname === "/api/v1/fanouts")
        body = { items: [], revision: 0, next_cursor: null };
      if (url.pathname === "/api/v1/recipes")
        body = {
          items: Object.entries(recipeConfig).map(([id, r]) => ({
            id,
            name: r.name,
            version: 1,
            steps: r.steps.map(([id, target, risk, depends_on]) => ({
              id,
              target,
              risk,
              depends_on,
            })),
          })),
        };
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    }
    let file: string;
    if (url.pathname === "/") file = resolve(root, "portal/index.html");
    else if (url.pathname.startsWith("/portal-assets/"))
      file = resolve(root, "portal", url.pathname.slice(1));
    else if (url.pathname.startsWith("/workshop/")) {
      file = resolve(root, url.pathname.slice(1));
      if (!existsSync(file) || !statSync(file).isFile())
        file = resolve(root, "workshop/index.html");
    } else
      return route.fulfill({
        status: 404,
        body: "Legacy routes are not fetched by this isolated candidate test",
      });
    if (!file.startsWith(root + sep) || !existsSync(file)) return route.abort();
    return route.fulfill({
      status: 200,
      contentType:
        (
          {
            ".html": "text/html",
            ".js": "text/javascript",
            ".css": "text/css",
            ".json": "application/json",
            ".svg": "image/svg+xml",
          } as Record<string, string>
        )[extname(file)] ?? "application/octet-stream",
      body: readFileSync(file),
    });
  });
  return { requests, external };
}
test("compiled public portal has isolated assets and never calls legacy or private APIs", async ({
  page,
  context,
}) => {
  const h = await host(context, false);
  await page.goto(origin + "/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    "想法很多",
  );
  await expect(page.locator(".header-work")).toHaveAttribute(
    "href",
    "/workshop/",
  );
  expect(
    h.requests.some(
      (r) =>
        r.path.startsWith("/assets/") ||
        r.path.startsWith("/api/") ||
        r.path.startsWith("/v1/") ||
        r.method !== "GET",
    ),
  ).toBe(false);
  expect(h.external).toEqual([]);
  mkdirSync("evidence/us", { recursive: true });
  await page.screenshot({
    path: "evidence/us/public-portal.png",
    fullPage: true,
  });
});
test("compiled /workshop refuses an anonymous visitor and does not mint a local actor", async ({
  page,
  context,
}) => {
  const h = await host(context, false);
  await page.goto(origin + "/workshop/");
  await expect(
    page.getByRole("heading", { name: "401", exact: true }),
  ).toBeVisible();
  expect(
    h.requests.some((r) => r.method !== "GET" || r.path === "/local/session"),
  ).toBe(false);
  expect(h.external).toEqual([]);
});
test("same-origin private draft reaches the authenticated /workshop safely in read-only mode", async ({
  page,
  context,
}) => {
  const h = await host(context, true);
  await page.goto(origin + "/");
  await page
    .getByLabel("这次想推进的工作")
    .fill("private research intent for isolated HTTPS test");
  await page.getByRole("button", { name: "方案开发", exact: true }).click();
  await page.getByRole("button", { name: "到工作坊检查" }).click();
  await expect(page).toHaveURL(
    origin + "/workshop/workbench/fanout?recipe=decision",
  );
  await expect(page.getByLabel("多平台工作意图")).toHaveValue(
    "private research intent for isolated HTTPS test",
  );
  await expect(
    page.getByRole("button", { name: "一键发起协同流水线" }),
  ).toBeDisabled();
  expect(page.url()).not.toContain("private");
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "us_fixture_session",
  );
  expect(
    await page.evaluate(() =>
      navigator.serviceWorker.getRegistrations().then((r) => r.length),
    ),
  ).toBe(0);
  expect(
    h.requests.some((r) => r.method !== "GET" || r.path === "/local/session"),
  ).toBe(false);
  expect(h.external).toEqual([]);
  await page.reload();
  await expect(page.getByLabel("多平台工作意图")).toHaveValue(
    "private research intent for isolated HTTPS test",
  );
  await context.clearCookies();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "401", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("多平台工作意图")).toHaveCount(0);
});
