// Local candidate static host; same BFF boundary as Vite. Never a production TLS/auth server.
import { randomUUID } from "node:crypto";
import { createServer, request as upstream } from "node:http";
import { readFileSync, statSync } from "node:fs";
import { resolve, extname, sep } from "node:path";
const root = resolve("dist");
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};
const server = createServer((req, res) => {
  const path = new URL(req.url, "http://127.0.0.1:5174").pathname;
  if (path.startsWith("/api/") || path.startsWith("/local/")) {
    const out = upstream(
      {
        host: "127.0.0.1",
        port: 8128,
        path: req.url,
        method: req.method,
        headers: req.headers,
      },
      (r) => {
        res.writeHead(r.statusCode, r.headers);
        r.pipe(res);
      },
    );
    out.on("error", () => {
      if (!res.headersSent)
        res.writeHead(503, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          error: {
            code: "local_bff_offline",
            message: "Local session service unavailable",
          },
          trace_id: randomUUID(),
        }),
      );
    });
    res.on("close", () => out.destroy());
    req.pipe(out);
    req.on("aborted", () => out.destroy());
    return;
  }
  if (!["GET", "HEAD"].includes(req.method)) {
    res.writeHead(405);
    res.end();
    return;
  }
  let decoded;
  try {
    decoded = decodeURIComponent(path);
  } catch {
    res.writeHead(400);
    res.end();
    return;
  }
  let file = resolve(root, "." + decoded);
  if (
    (file !== root && !file.startsWith(root + sep)) ||
    decoded.split("/").some((p) => p.startsWith("."))
  ) {
    res.writeHead(403);
    res.end();
    return;
  }
  try {
    if (statSync(file).isDirectory()) file = resolve(file, "index.html");
    if (!statSync(file).isFile()) throw Error();
  } catch {
    const entityRoute = /^\/(tasks|nodes|services|agents)\/[^/]+\/?$/.test(
      decoded,
    );
    if (extname(path) && !entityRoute) {
      res.writeHead(404);
      res.end();
      return;
    }
    file = resolve(root, "index.html");
  }
  try {
    const b = readFileSync(file);
    res.writeHead(200, {
      "Content-Type": types[extname(file)] ?? "application/octet-stream",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    res.end(req.method === "HEAD" ? undefined : b);
  } catch {
    res.writeHead(503);
    res.end("Local static build missing; run node scripts/mw.mjs build");
  }
});
server.listen(5174, "127.0.0.1", () =>
  console.log("Local static candidate 127.0.0.1:5174"),
);
process.on("SIGTERM", () => server.close(() => process.exit(0)));
