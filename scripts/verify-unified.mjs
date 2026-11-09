import { spawn, execFileSync } from "node:child_process";
import {
  readFileSync,
  writeFileSync,
  existsSync,
  mkdirSync,
  openSync,
  closeSync,
  rmSync,
} from "node:fs";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
const backend = resolve(fileURLToPath(new URL("..", import.meta.url)));
const front = join(backend, "frontend");
const py =
  process.env.MW_PYTHON ??
  (existsSync(join(backend, ".venv/bin/python"))
    ? join(backend, ".venv/bin/python")
    : "python3");
const out = join(front, "evidence/release");
mkdirSync(out, { recursive: true });
const git = (cwd, ...args) =>
  execFileSync("git", args, { cwd, encoding: "utf8" }).trim();
const heads = {
  frontend: git(front, "rev-parse", "HEAD"),
  backend: git(backend, "rev-parse", "HEAD"),
};
if (git(backend, "status", "--porcelain"))
  throw Error("Clean unified source required");
const hash = (p) => createHash("sha256").update(readFileSync(p)).digest("hex");
const sha = hash(join(backend, "contracts/openapi.yaml"));
if (
  existsSync(join(front, "contracts/openapi.yaml")) ||
  existsSync(join(front, "contracts/CONTRACT-LOCK.json"))
)
  throw Error("Duplicate active frontend contract forbidden");
for (const dir of [backend])
  if (
    JSON.parse(readFileSync(join(dir, "contracts/CONTRACT-LOCK.json")))
      .sha256 !== sha
  )
    throw Error("Lock mismatch");
const steps = [];
let stack;
function save(status) {
  writeFileSync(
    join(out, "integrated-release.json"),
    JSON.stringify(
      {
        unified_commit: heads.frontend,
        tree: git(backend, "rev-parse", "HEAD^{tree}"),
        heads,
        contract_sha256: sha,
        paths: 41,
        operations: 43,
        status,
        steps,
        deployed: false,
        approved: "LOCAL_ONLY",
        pg_runtime: "NOT_RUN",
      },
      null,
      2,
    ),
  );
}
async function run(name, cmd, args, cwd = front, env = {}) {
  console.log("Verifying", name);
  const fd = openSync(join(out, `${name}.log`), "w");
  const t = Date.now();
  const child = spawn(cmd, args, {
    cwd,
    stdio: ["ignore", fd, fd],
    env: { ...process.env, ...env },
  });
  const code = await new Promise((ok, fail) => {
    child.once("error", fail);
    child.once("close", ok);
  });
  closeSync(fd);
  steps.push({ name, exit_code: code, elapsed_ms: Date.now() - t });
  save("RUNNING");
  if (code !== 0)
    throw Error(`${name} failed: inspect evidence/release/${name}.log`);
  console.log("Passed", name);
}
async function stopStack() {
  if (!stack) return;
  const owned = stack;
  stack = undefined;
  owned.kill("SIGTERM");
  await Promise.race([
    new Promise((r) => owned.once("close", r)),
    new Promise((r) => setTimeout(r, 5000)),
  ]);
  if (owned.exitCode === null) owned.kill("SIGKILL");
}
try {
  await run("baseline-retention", py, ["scripts/check_baseline.py"], backend);
  await run("sensitive-scan", py, ["scripts/security_check.py"], backend);
  await run(
    "process-ownership",
    py,
    [
      "-m",
      "pytest",
      "scripts/tests",
      "-q",
      `--junitxml=${join(out, "process-ownership.xml")}`,
    ],
    backend,
  );
  await run(
    "shared-contract-sdk",
    process.execPath,
    ["scripts/mw.mjs", "contract"],
    backend,
  );
  await run(
    "backend-normal",
    py,
    [
      "-m",
      "pytest",
      "backend/tests",
      "tests",
      "-q",
      `--junitxml=${join(out, "backend-normal.xml")}`,
    ],
    backend,
    { MWCP_PROBE_MODE: "test" },
  );
  const reversed = String.raw`import subprocess,sys; p=subprocess.run([sys.executable,'-m','pytest','backend/tests','tests','--collect-only','-q'],capture_output=True,text=True,check=True); ids=[s for s in p.stdout.splitlines() if s.startswith(('backend/tests/','tests/')) and '::' in s]; assert ids; sys.exit(subprocess.run([sys.executable,'-m','pytest',*reversed(ids),'-q','--junitxml='+sys.argv[1]]).returncode)`;
  await run(
    "backend-reverse",
    py,
    ["-c", reversed, join(out, "backend-reverse.xml")],
    backend,
    { MWCP_PROBE_MODE: "test" },
  );
  await run(
    "dbpg-offline",
    py,
    [
      "-m",
      "pytest",
      "dbpg/tests",
      "-q",
      `--junitxml=${join(out, "dbpg-offline.xml")}`,
    ],
    backend,
    { PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1" },
  );
  await run("route-coverage", py, ["tools/route_coverage.py"], backend);
  await run("runtime-contract", py, [
    "integration/audit_glm.py",
    "--backend",
    join(backend, "backend"),
    "--output",
    join(out, "runtime-contract.json"),
  ]);
  if (JSON.parse(readFileSync(join(out, "runtime-contract.json"))).failed !== 0)
    throw Error("Runtime contract failures");
  await run("bff", py, [
    "-m",
    "pytest",
    "integration/test_bff.py",
    "-q",
    `--junitxml=${join(out, "bff.xml")}`,
  ]);
  await run("frontend-check", "npm", ["run", "check"], front, {
    VITE_API_MODE: "loopback",
  });
  await run(
    "static-build",
    process.execPath,
    ["scripts/mw.mjs", "build"],
    backend,
  );
  await run("mock-e2e", "npm", ["run", "e2e"]);
  rmSync(join(front, "evidence/live-integration/screenshots"), {
    recursive: true,
    force: true,
  });
  const fd = openSync(join(out, "local-stack.log"), "w");
  stack = spawn(
    process.execPath,
    ["scripts/start-integration.mjs", join(backend, "backend"), "--static"],
    {
      cwd: front,
      stdio: ["ignore", fd, fd],
      env: {
        ...process.env,
        MW_PYTHON: py,
        MW_INTEGRATION_REPORT: join(out, "loopback-http.json"),
      },
    },
  );
  closeSync(fd);
  const start = Date.now();
  let ready = false;
  while (Date.now() - start < 30000) {
    if (stack.exitCode !== null) throw Error("Local stack exited before ready");
    try {
      const a = await fetch("http://127.0.0.1:5174/");
      const b = await fetch("http://127.0.0.1:8128/local/session");
      const c = await fetch("http://127.0.0.1:8127/api/v1/health/live");
      if (a.status === 200 && b.status === 405 && c.status === 200) {
        ready = true;
        break;
      }
    } catch {
      /* wait for owned loopback services to bind */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!ready) throw Error("Local stack startup timeout");
  await run("live-e2e", "node_modules/.bin/playwright", [
    "test",
    "-c",
    "playwright.integration.config.ts",
  ]);
  const pids = JSON.parse(
    readFileSync(join(front, "evidence/local-processes.json")),
  );
  const memory = {};
  for (const [role, pid] of Object.entries(pids)) {
    if (typeof pid !== "number") continue;
    try {
      memory[role] = Object.fromEntries(
        readFileSync(`/proc/${pid}/status`, "utf8")
          .split("\n")
          .filter((l) => l.startsWith("VmRSS:") || l.startsWith("VmHWM:"))
          .map((l) => l.split(":").map((s) => s.trim())),
      );
    } catch {
      memory[role] = "UNAVAILABLE";
    }
  }
  writeFileSync(
    join(out, "local-memory.json"),
    JSON.stringify(
      {
        scope:
          "Observed local API+BFF and static candidate processes; not a US deployment/PG capacity claim",
        memory,
      },
      null,
      2,
    ),
  );
  await stopStack();
  await run("prefixed-deployment", process.execPath, ["scripts/check-prefixed.mjs"]);
  await run("unified-lifecycle", py, ["scripts/lifecycle_smoke.py"], backend);
  if (git(backend, "status", "--porcelain"))
    throw Error("Verification mutated source");
  save("PASSED_UNIFIED_LOCAL_RC");
  console.log("Passed joint local RC", heads, sha);
} catch (e) {
  save("FAILED");
  throw e;
} finally {
  await stopStack();
}
