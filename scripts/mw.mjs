import { spawn, spawnSync, execFileSync } from "node:child_process";
import {
  readFileSync,
  existsSync,
  mkdirSync,
  writeFileSync,
  openSync,
  closeSync,
  unlinkSync,
} from "node:fs";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
const front = join(root, "frontend"),
  runtime = join(root, ".runtime"),
  stateFile = join(runtime, "local.json");
const py =
  process.env.MW_PYTHON ??
  (existsSync(join(root, ".venv/bin/python"))
    ? join(root, ".venv/bin/python")
    : "python3");
const command = process.argv[2] ?? "help";
const run = (cmd, args, cwd = root, env = {}) => {
  const r = spawnSync(cmd, args, {
    cwd,
    stdio: "inherit",
    env: { ...process.env, ...env },
  });
  if (r.error) throw r.error;
  if (r.status !== 0) process.exit(r.status ?? 1);
};
// 进程起始 ticks：Linux /proc（权威语义）。macOS 无 /proc，降级为 ps 的进程启动时刻
// （lstart→epoch 秒），与 pid+nonce 共同构成所有权判据；停止仍拒绝复用/外来 pid。
const ticks = (pid) => {
  if (existsSync(`/proc/${pid}/stat`))
    return readFileSync(`/proc/${pid}/stat`, "utf8")
      .split(") ")[1]
      .split(" ")[19];
  const ps = spawnSync("ps", ["-o", "lstart=,epoch=", "-p", String(pid)], {
    encoding: "utf8",
  });
  if (ps.status !== 0 || !ps.stdout.trim()) return "unknown";
  const [, epoch] = ps.stdout
    .trim()
    .split(/\s+(?=\d{5,})/)
    .reverse();
  return epoch?.trim() ?? "unknown";
};
if (command === "supervise") {
  const nonce = process.argv[3];
  const child = spawn(
    process.execPath,
    [
      "scripts/start-integration.mjs",
      "../backend",
      ...(process.argv.includes("--static") ? ["--static"] : []),
    ],
    {
      cwd: front,
      stdio: "inherit",
      env: { ...process.env, MW_PYTHON: py, MW_STACK_OWNER_NONCE: nonce },
    },
  );
  writeFileSync(
    stateFile,
    JSON.stringify({
      pid: process.pid,
      start_ticks: ticks(process.pid),
      nonce,
      root,
      child_pid: child.pid,
    }),
    { mode: 0o600 },
  );
  const stop = () => child.kill("SIGTERM");
  process.on("SIGTERM", stop);
  process.on("SIGINT", stop);
  child.on("exit", (code) => {
    try {
      const s = JSON.parse(readFileSync(stateFile));
      if (s.nonce === nonce) unlinkSync(stateFile);
    } catch {}
    process.exit(code ?? 1);
  });
} else if (command === "start") {
  mkdirSync(runtime, { recursive: true, mode: 0o700 });
  if (existsSync(stateFile))
    throw Error(
      "Owned state exists; run stop or inspect .runtime/local.json before starting again",
    );
  const fd = openSync(join(runtime, "local.log"), "a", 0o600),
    nonce = randomUUID();
  const child = spawn(
    process.execPath,
    [
      fileURLToPath(import.meta.url),
      "supervise",
      nonce,
      ...(process.argv.includes("--static") ? ["--static"] : []),
    ],
    {
      cwd: root,
      detached: true,
      stdio: ["ignore", fd, fd],
      env: { ...process.env, MW_PYTHON: py },
    },
  );
  closeSync(fd);
  child.unref();
  let ready = false;
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 250));
    if (child.exitCode !== null) break;
    if (!existsSync(stateFile)) continue;
    try {
      const proof = JSON.parse(
        readFileSync(join(front, "evidence/local-processes.json")),
      );
      if (proof.owner_nonce !== nonce) continue;
    } catch {
      continue;
    }
    try {
      const a = await fetch("http://127.0.0.1:5174/"),
        b = await fetch("http://127.0.0.1:8127/api/v1/health/live");
      if (a.ok && b.ok) {
        ready = true;
        break;
      }
    } catch {}
  }
  if (!ready) {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {}
    throw Error(
      "Local startup failed; inspect .runtime/local.log. Existing services were not reused or stopped.",
    );
  }
  console.log(
    "Local synthetic console: http://127.0.0.1:5174; stop with node scripts/mw.mjs stop",
  );
} else if (command === "stop") {
  if (!existsSync(stateFile)) {
    console.log("No owned local stack state");
    process.exit(0);
  }
  const s = JSON.parse(readFileSync(stateFile));
  let alive = true;
  try {
    process.kill(s.pid, 0);
  } catch (e) {
    if (e.code === "ESRCH") alive = false;
    else throw e;
  }
  if (!alive) {
    unlinkSync(stateFile);
    console.log("Removed stale owned state; no process signalled");
    process.exit(0);
  }
  // macOS 无 /proc/cmdline：用 ps 命令行等价判定（语义一致：找 supervise+nonce）
  const cmdline = existsSync(`/proc/${s.pid}/cmdline`)
    ? readFileSync(`/proc/${s.pid}/cmdline`, "utf8")
    : (spawnSync("ps", ["-o", "command=", "-p", String(s.pid)], {
        encoding: "utf8",
      }).stdout ?? "");
  if (
    s.root !== root ||
    ticks(s.pid) !== s.start_ticks ||
    !cmdline.includes("supervise") ||
    !cmdline.includes(s.nonce)
  )
    throw Error("Process ownership mismatch; refusing to signal");
  process.kill(-s.pid, "SIGTERM");
  for (let i = 0; i < 100; i++) {
    try {
      process.kill(s.pid, 0);
    } catch {
      break;
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  console.log("Stopped only this repository's owned local process group");
} else if (command === "test")
  run(process.execPath, ["scripts/verify-unified.mjs"]);
else if (command === "contract") {
  run("npm", ["run", "generate"], front);
  run("npm", ["run", "contract-sha-check"], front);
  run("git", [
    "diff",
    "--exit-code",
    "--",
    "frontend/src/api/generated",
    "frontend/src/mocks/schemas.json",
    "frontend/src/mocks/fanout-recipes.json",
  ]);
  run(py, ["tools/route_coverage.py"]);
  run(py, ["tools/contract_check.py"]);
} else if (["build", "build-session"].includes(command)) {
  const session = command === "build-session";
  const origin = process.env.MW_PUBLIC_ORIGIN;
  if (
    session &&
    (!origin ||
      new URL(origin).protocol !== "https:" ||
      new URL(origin).origin !== origin)
  )
    throw Error(
      "build-session requires MW_PUBLIC_ORIGIN as an exact HTTPS origin",
    );
  if (session && process.env.VITE_LOCAL_API_ORIGIN)
    throw Error(
      "Remove VITE_LOCAL_API_ORIGIN before building the public session candidate",
    );
  if (
    session &&
    ![undefined, "disabled", "enabled"].includes(process.env.MW_SESSION_WRITES)
  )
    throw Error(
      "MW_SESSION_WRITES must be disabled or explicitly enabled after server validation",
    );
  const webBase = process.env.MW_WEB_BASE ?? (session ? "/app/" : "/");
  run("npm", ["run", "build"], front, {
    VITE_API_MODE: session ? "session" : "loopback",
    MW_WEB_BASE: webBase,
    ...(session
      ? {
          VITE_PUBLIC_ORIGIN: origin,
          VITE_SESSION_WRITES: process.env.MW_SESSION_WRITES ?? "disabled",
        }
      : {}),
  });
  writeFileSync(
    join(front, "dist/build-meta.json"),
    JSON.stringify(
      {
        head: execFileSync("git", ["rev-parse", "HEAD"], {
          cwd: root,
          encoding: "utf8",
        }).trim(),
        mode: session ? "session" : "loopback",
        public_origin: session ? origin : null,
        read_only: session && process.env.MW_SESSION_WRITES !== "enabled",
        web_base: webBase,
        contract_sha256: JSON.parse(
          readFileSync(join(root, "contracts/CONTRACT-LOCK.json")),
        ).sha256,
      },
      null,
      2,
    ),
  );
} else if (command === "build-us") {
  run(process.execPath, [
    "scripts/build_us_candidate.mjs",
    ...process.argv.slice(3),
  ]);
} else if (command === "package") {
  run(process.execPath, ["scripts/mw.mjs", "build"]);
  run(py, ["scripts/package_release.py"]);
} else if (command === "security") run(py, ["scripts/security_check.py"]);
else if (command === "dependencies") {
  run("npm", ["audit", "--audit-level=high"], front);
  run(process.env.MW_AUDIT_PYTHON ?? py, [
    "-m",
    "pip_audit",
    "-r",
    "backend/requirements.lock",
    "--strict",
  ]);
} else
  console.log(
    "node scripts/mw.mjs start [--static] | stop | test | contract | build | build-session | build-us [--preview] | package | security | dependencies",
  );
