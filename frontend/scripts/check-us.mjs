import { spawnSync, execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
function run(command, args, cwd = process.cwd(), env = {}) {
  const r = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    env: { ...process.env, ...env },
  });
  if (r.error) throw r.error;
  if (r.status !== 0)
    throw Error("US static candidate verification failed: " + r.status);
}
const preview = process.argv.includes("--preview");
run(
  process.execPath,
  ["scripts/mw.mjs", "build-us", ...(preview ? ["--preview"] : [])],
  resolve(".."),
);
const pointer = JSON.parse(readFileSync("../release/us-candidate/LATEST.json"));
const head = execFileSync("git", ["rev-parse", "HEAD"], {
  encoding: "utf8",
}).trim();
if (pointer.head !== head || (!preview && pointer.source_dirty))
  throw Error("Candidate source identity mismatch");
run(
  "node_modules/.bin/playwright",
  ["test", "-c", "playwright.us.config.ts"],
  process.cwd(),
  { MW_US_CANDIDATE_DIR: pointer.directory },
);
