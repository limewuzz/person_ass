import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import YAML from "yaml";
import { execFileSync } from "node:child_process";
const bytes = readFileSync("../contracts/openapi.yaml");
const sha = createHash("sha256").update(bytes).digest("hex");
if (
  existsSync("../contracts/CONTRACT-LOCK.json") &&
  JSON.parse(readFileSync("../contracts/CONTRACT-LOCK.json")).sha256 !== sha
)
  throw Error("Generation input differs from frozen lock");
if (!existsSync("node_modules/.bin/openapi-typescript"))
  throw Error("Install locked frontend dependencies before SDK generation");
{
  execFileSync(
    "node_modules/.bin/openapi-typescript",
    [
      "../contracts/openapi.yaml",
      "--empty-objects-unknown",
      "-o",
      "src/api/generated/schema.ts",
    ],
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

const spec = YAML.parse(bytes.toString("utf8"));
const methods = new Set([
  "get",
  "post",
  "put",
  "patch",
  "delete",
  "head",
  "options",
  "trace",
]);
const operations = Object.entries(spec.paths).flatMap(([path, item]) =>
  Object.entries(item)
    .filter(([method]) => methods.has(method))
    .map(([method, op]) => ({
      path,
      method,
      operationId: op.operationId,
      x_phase: op["x-phase"],
      responses: Object.fromEntries(
        Object.entries(op.responses).map(([status, response]) => [
          status,
          response.content?.["application/json"]?.schema ?? {},
        ]),
      ),
      request: op.requestBody?.content?.["application/json"]?.schema ?? null,
    })),
);
writeFileSync(
  "src/api/generated/operations.json",
  JSON.stringify(operations, null, 2) + "\n",
);
writeFileSync(
  "src/mocks/schemas.json",
  JSON.stringify(spec.components.schemas) + "\n",
);

writeFileSync(
  "src/mocks/fanout-recipes.json",
  readFileSync("../backend/fanout/recipes.json"),
);
