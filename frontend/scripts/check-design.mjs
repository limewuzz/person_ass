import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
const manifest = JSON.parse(readFileSync("docs/DESIGN-HASHES.json"));
for (const [path, expected] of Object.entries(manifest)) {
  const bytes = readFileSync(path);
  if (
    bytes.length !== expected.bytes ||
    createHash("sha256").update(bytes).digest("hex") !== expected.sha256
  )
    throw Error(`Historical design changed: ${path}`);
}
console.log("V1 and Prism original bytes preserved");
