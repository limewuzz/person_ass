// Start only owned, loopback synthetic processes. The first launcher port check
// rejects existing services. Always stop this child and restore the root build.
import { spawn, spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
const root = resolve(".."),
  nonce = randomUUID(),
  env = { ...process.env, MW_WEB_BASE: "/app/", MW_STACK_OWNER_NONCE: nonce };
function run(cmd, args, cwd = process.cwd(), extra = env) {
  const r = spawnSync(cmd, args, { cwd, env: extra, stdio: "inherit" });
  if (r.error) throw r.error;
  if (r.status !== 0)
    throw Error(`Prefix verification command failed (${r.status})`);
}
run(process.execPath, ["scripts/mw.mjs", "build"], root);
const stack = spawn(
  process.execPath,
  ["scripts/start-integration.mjs", "../backend", "--static"],
  { env, stdio: "inherit" },
);
try {
  let ready = false;
  for (let i = 0; i < 120; i++) {
    if (stack.exitCode !== null) throw Error("Owned prefix stack exited");
    try {
      if (
        JSON.parse(readFileSync("evidence/local-processes.json"))
          .owner_nonce !== nonce
      ) {
        await new Promise((r) => setTimeout(r, 250));
        continue;
      }
      const r = await fetch("http://127.0.0.1:5174/app/build-meta.json");
      const bff = await fetch("http://127.0.0.1:8128/api/v1/me");
      const raw = await fetch("http://127.0.0.1:8127/api/v1/health/live");
      if (
        r.ok &&
        (await r.json()).web_base === "/app/" &&
        bff.status === 401 &&
        raw.status === 200
      ) {
        ready = true;
        break;
      }
    } catch {
      /* owned stack starts asynchronously */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!ready) throw Error("Owned prefix stack not ready");
  run("node_modules/.bin/playwright", [
    "test",
    "-c",
    "playwright.prefix.config.ts",
  ]);
} finally {
  stack.kill("SIGTERM");
  if (stack.exitCode === null) await new Promise((r) => stack.once("close", r));
  run(process.execPath, ["scripts/mw.mjs", "build"], root, {
    ...process.env,
    MW_WEB_BASE: "/",
  });
}
