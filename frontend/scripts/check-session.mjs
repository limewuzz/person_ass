import { spawnSync } from "node:child_process";
function run(cmd, args, env = process.env, cwd = process.cwd()) {
  const r = spawnSync(cmd, args, { env, cwd, stdio: "inherit" });
  if (r.error) throw r.error;
  if (r.status !== 0)
    throw Error(`Session candidate check failed (${r.status})`);
}
try {
  run(
    process.execPath,
    ["scripts/mw.mjs", "build-session"],
    {
      ...process.env,
      MW_PUBLIC_ORIGIN: "https://workspace.test",
      MW_WEB_BASE: "/app/",
      MW_SESSION_WRITES: "disabled",
    },
    "..",
  );
  run("node_modules/.bin/playwright", [
    "test",
    "-c",
    "playwright.session.config.ts",
  ]);
} finally {
  run(
    process.execPath,
    ["scripts/mw.mjs", "build"],
    { ...process.env, MW_WEB_BASE: "/" },
    "..",
  );
}
