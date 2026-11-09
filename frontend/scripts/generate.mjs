import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { parse } from "yaml";
const bytes = readFileSync("../contracts/openapi.yaml"),
  oas = parse(bytes.toString());
const sha = createHash("sha256").update(bytes).digest("hex");
if (
  existsSync("../contracts/CONTRACT-LOCK.json") &&
  JSON.parse(readFileSync("../contracts/CONTRACT-LOCK.json")).sha256 !== sha
)
  throw Error("Generation input differs from frozen lock");
execFileSync(
  "node_modules/.bin/openapi-typescript",
  ["../contracts/openapi.yaml", "-o", "src/api/generated/schema.ts"],
  { stdio: "inherit" },
);
writeFileSync(
  "src/api/generated/contract.json",
  JSON.stringify(
    {
      contract_sha256: createHash("sha256").update(bytes).digest("hex"),
      status: existsSync("../contracts/CONTRACT-LOCK.json")
        ? "LOCAL_CONTRACT_LOCKED"
        : "CANDIDATE_NOT_GLM_LOCKED",
      paths: 41,
      operations: 43,
    },
    null,
    2,
  ),
);
writeFileSync("src/mocks/schemas.json", JSON.stringify(oas.components.schemas));
const ops = Object.entries(oas.paths).flatMap(([path, p]) =>
  Object.entries(p)
    .filter(([m]) => ["get", "post"].includes(m))
    .map(([method, o]) => ({
      path,
      method,
      operationId: o.operationId,
      responses: Object.fromEntries(
        Object.entries(o.responses)
          .filter(([k]) => k.startsWith("2"))
          .map(([k, v]) => [k, v.content?.["application/json"]?.schema ?? {}]),
      ),
      request: o.requestBody?.content?.["application/json"]?.schema ?? null,
    })),
);
writeFileSync(
  "src/api/generated/operations.json",
  JSON.stringify(ops, null, 2),
);
