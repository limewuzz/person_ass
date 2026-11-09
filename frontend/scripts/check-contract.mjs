import { readFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import { parse } from "yaml";
const bytes = readFileSync("../contracts/openapi.yaml"),
  hash = createHash("sha256").update(bytes).digest("hex");
const input = JSON.parse(readFileSync("src/api/generated/contract.json"));
const oas = parse(bytes.toString()),
  ops = Object.values(oas.paths).flatMap((v) =>
    Object.keys(v).filter((k) =>
      ["get", "post", "put", "patch", "delete"].includes(k),
    ),
  );
if (
  hash !== input.contract_sha256 ||
  Object.keys(oas.paths).length !== 41 ||
  ops.length !== 43
)
  throw Error("Contract drift");
if (existsSync("../contracts/CONTRACT-LOCK.json")) {
  const lock = JSON.parse(readFileSync("../contracts/CONTRACT-LOCK.json"));
  if ((lock.openapi_sha256 ?? lock.sha256) !== hash)
    throw Error("GLM lock mismatch");
  console.log("GLM lock matches");
} else if (process.argv.includes("--require-lock"))
  throw Error("GLM final lock missing: integration blocked");
else
  console.log(
    "Candidate matches; GLM final lock missing, integration NOT VERIFIED",
  );
console.log(hash, "41 paths / 43 operations");
