export type ApiMode = "mock" | "loopback" | "session";
export function assertLocalBase(base: string, pageOrigin: string) {
  const u = new URL(base, pageOrigin);
  if (
    !["http:", "https:"].includes(u.protocol) ||
    u.username ||
    u.password ||
    ["3100", "8765", "8123"].includes(u.port) ||
    !["127.0.0.1", "localhost"].includes(u.hostname)
  )
    throw Error("Only new loopback API allowed");
  return u.origin;
}
export function apiConfig(
  env: {
    mode?: string;
    localOrigin?: string;
    publicOrigin?: string;
    sessionWrites?: string;
  },
  pageOrigin: string,
) {
  const mode = env.mode ?? "mock";
  if (!["mock", "loopback", "session"].includes(mode))
    throw Error("Unknown API mode; refusing mock fallback");
  if (mode !== "session") assertLocalBase(pageOrigin, pageOrigin);
  if (mode !== "session")
    return {
      mode: mode as ApiMode,
      origin: assertLocalBase(env.localOrigin ?? pageOrigin, pageOrigin),
      canWrite: true,
    };
  if (!env.publicOrigin || env.localOrigin)
    throw Error(
      "Session mode requires an explicit public origin and no local override",
    );
  const expected = new URL(env.publicOrigin),
    page = new URL(pageOrigin);
  if (
    expected.protocol !== "https:" ||
    expected.origin !== env.publicOrigin ||
    expected.origin !== page.origin ||
    expected.username ||
    expected.password ||
    ["3100", "8765", "8123"].includes(expected.port) ||
    ["127.0.0.1", "localhost"].includes(expected.hostname)
  )
    throw Error(
      "Session API must use the configured same-origin HTTPS endpoint",
    );
  return {
    mode: "session" as const,
    origin: expected.origin,
    canWrite: env.sessionWrites === "enabled",
  };
}
