import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
const bytes = readFileSync("../contracts/openapi.yaml"),
  hash = createHash("sha256").update(bytes).digest("hex");
const input = JSON.parse(readFileSync("src/api/generated/contract.json"));
const ops = JSON.parse(readFileSync("src/api/generated/operations.json"));
if (
  hash !== input.contract_sha256 ||
  input.paths !== 79 ||
  input.operations !== 95 ||
  ops.length !== 95
)
  throw Error("Contract drift");
if (existsSync("../contracts/CONTRACT-LOCK.json")) {
  const lock = JSON.parse(readFileSync("../contracts/CONTRACT-LOCK.json"));
  if ((lock.openapi_sha256 ?? lock.sha256) !== hash)
    throw Error("GLM lock mismatch");
  console.log("GLM lock matches");
} else if (process.argv.includes("--require-lock"))
  throw Error("GLM final lock missing: integration blocked");
console.log(hash, `${input.paths} paths / ${input.operations} operations`);
