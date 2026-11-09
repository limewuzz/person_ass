import { execFileSync, spawn } from "node:child_process";
import { readFileSync, existsSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { createHash } from "node:crypto";
import { createServer } from "node:net";
execFileSync(
  process.execPath,
  ["scripts/check-contract.mjs", "--require-lock"],
  { stdio: "inherit" },
);
const backend = resolve(process.argv[2] ?? "../backend");
if (!existsSync(join(backend, "app.py")))
  throw Error("Provide isolated GLM backend directory");
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
if (
  hash(readFileSync(join(backend, "../contracts/openapi.yaml"))) !==
  hash(readFileSync("../contracts/openapi.yaml"))
)
  throw Error("Backend contract mismatch");
for (const port of [8127, 8128, 5174])
  await new Promise((ok, fail) => {
    const s = createServer();
    s.once("error", () =>
      fail(Error(`Development port ${port} occupied; refusing to reuse`)),
    );
    s.listen(port, "127.0.0.1", () => s.close(ok));
  });
const stack = spawn(
  process.env.MW_PYTHON ?? "python3",
  ["integration/local_stack.py", "--backend", backend],
  { stdio: "inherit" },
);
const webEnv = { ...process.env, VITE_API_MODE: "loopback" };
delete webEnv.VITE_LOCAL_API_ORIGIN;
const isStatic = process.argv.includes("--static");
const web = spawn(
  isStatic ? process.execPath : "node_modules/.bin/vite",
  isStatic
    ? ["integration/static_server.mjs"]
    : ["--host", "127.0.0.1", "--port", "5174", "--strictPort"],
  { stdio: "inherit", env: webEnv },
);
mkdirSync("evidence", { recursive: true });
writeFileSync(
  "evidence/local-processes.json",
  JSON.stringify(
    {
      backend_bff_pid: stack.pid,
      frontend_dev_pid: web.pid,
      owner_nonce: process.env.MW_STACK_OWNER_NONCE ?? null,
    },
    null,
    2,
  ),
);
function stop() {
  stack.kill("SIGTERM");
  web.kill("SIGTERM");
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
stack.on("exit", (code) => {
  web.kill("SIGTERM");
  process.exitCode = code ?? 1;
});
web.on("exit", () => stack.kill("SIGTERM"));
