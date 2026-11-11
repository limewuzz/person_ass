// Assemble a static, read-only US candidate. This script never deploys or logs in.
import { spawnSync, execFileSync } from "node:child_process";
import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  statSync,
  cpSync,
} from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const git = (...args) =>
  execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
const dirty = !!git("status", "--porcelain");
if (dirty && !process.argv.includes("--preview"))
  throw Error(
    "A release candidate requires clean source. Use --preview only for local design review.",
  );
const origin = process.env.MW_PUBLIC_ORIGIN ?? "https://magicworkshop.fun";
if (new URL(origin).origin !== origin || new URL(origin).protocol !== "https:")
  throw Error("An exact HTTPS public origin is required");
const prefix = "/workshop/";
if (
  process.env.MW_SESSION_WRITES &&
  process.env.MW_SESSION_WRITES !== "disabled"
)
  throw Error(
    "US candidate stays read-only until server authentication and execution gates pass",
  );
function run(command, args, cwd = root, env = {}) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
    env: { ...process.env, ...env },
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
run(process.execPath, ["scripts/mw.mjs", "build-session"], root, {
  MW_PUBLIC_ORIGIN: origin,
  MW_WEB_BASE: prefix,
  MW_SESSION_WRITES: "disabled",
});
run("npm", ["run", "build:portal"], join(root, "frontend"), {
  VITE_WORKSHOP_BASE: prefix,
});
const head = git("rev-parse", "HEAD"),
  tree = git("rev-parse", "HEAD^{tree}");
const candidateRoot = join(root, "release", "us-candidate");
mkdirSync(candidateRoot, { recursive: true });
const out = mkdtempSync(
  join(candidateRoot, head.slice(0, 12) + (dirty ? "-preview-" : "-")),
);
cpSync(join(root, "frontend/dist-portal"), join(out, "portal"), {
  recursive: true,
});
cpSync(join(root, "frontend/dist"), join(out, "workshop"), { recursive: true });
const lock = JSON.parse(
  readFileSync(join(root, "contracts/CONTRACT-LOCK.json")),
);
const meta = JSON.parse(readFileSync(join(out, "workshop/build-meta.json")));
if (
  meta.mode !== "session" ||
  meta.public_origin !== origin ||
  meta.web_base !== prefix ||
  meta.read_only !== true ||
  meta.contract_sha256 !== lock.sha256
)
  throw Error("Session build boundary mismatch");
const files = [];
function collect(dir, relative = "") {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name),
      rel = relative + name;
    if (statSync(path).isDirectory()) collect(path, rel + "/");
    else
      files.push({
        path: rel,
        bytes: statSync(path).size,
        sha256: createHash("sha256").update(readFileSync(path)).digest("hex"),
      });
  }
}
collect(out);
const manifest = {
  repository: "https://github.com/limewuzz/person_ass",
  head,
  tree,
  source_dirty: dirty,
  public_origin: origin,
  workshop_base: prefix,
  contract: lock,
  status: dirty ? "LOCAL_PREVIEW" : "STATIC_US_CANDIDATE",
  deployed: false,
  session_writes: false,
  authentication_runtime: "NOT_VERIFIED",
  postgres_runtime: "NOT_RUN",
  required_legacy_routes: [
    "/chat/",
    "/agent",
    "/models",
    "/usage/",
    "/v1/",
    "/assets/",
  ],
  files,
};
writeFileSync(
  join(out, "CANDIDATE-MANIFEST.json"),
  JSON.stringify(manifest, null, 2) + "\n",
);
writeFileSync(
  join(out, "SHA256SUMS.txt"),
  files.map((f) => `${f.sha256}  ${f.path}\n`).join(""),
);
writeFileSync(
  join(candidateRoot, "LATEST.json"),
  JSON.stringify({ head, directory: out, source_dirty: dirty }) + "\n",
);
console.log(
  JSON.stringify(
    {
      candidate_directory: out,
      status: manifest.status,
      origin,
      workshop_base: prefix,
      deployed: false,
    },
    null,
    2,
  ),
);
