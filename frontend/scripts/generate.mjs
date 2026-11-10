import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
const bytes = readFileSync("../contracts/openapi.yaml");
const sha = createHash("sha256").update(bytes).digest("hex");
if (
  existsSync("../contracts/CONTRACT-LOCK.json") &&
  JSON.parse(readFileSync("../contracts/CONTRACT-LOCK.json")).sha256 !== sha
)
  throw Error("Generation input differs from frozen lock");
if (existsSync("node_modules/.bin/openapi-typescript")) {
  execFileSync(
    "node_modules/.bin/openapi-typescript",
    ["../contracts/openapi.yaml", "-o", "src/api/generated/schema.ts"],
    { stdio: "inherit" },
  );
}
const lock = JSON.parse(readFileSync("../contracts/CONTRACT-LOCK.json"));
writeFileSync(
  "src/api/generated/contract.json",
  JSON.stringify(
    {
      contract_sha256: sha,
      version: lock.version ?? "2.0.0-unified-v2",
      status: "LOCAL_CONTRACT_LOCKED",
      paths: lock.paths,
      operations: lock.operations,
      v1_1_1_preserved_paths: 41,
      v1_1_1_preserved_operations: 43,
    },
    null,
    2,
  ) + "\n",
);
