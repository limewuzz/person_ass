import { it, expect } from "vitest";
import { apiConfig } from "../src/api/config";
it("never silently converts an unknown deployment mode into mock", () => {
  expect(() =>
    apiConfig({ mode: "prodution" }, "https://workspace.test"),
  ).toThrow("Unknown API mode");
});
it("keeps mocks and ephemeral issuers on loopback", () => {
  for (const mode of ["mock", "loopback"]) {
    expect(() =>
      apiConfig(
        { mode, localOrigin: "http://127.0.0.1:5174" },
        "https://workspace.test",
      ),
    ).toThrow("loopback");
    expect(() => apiConfig({ mode }, "https://workspace.test")).toThrow(
      "loopback",
    );
    expect(apiConfig({ mode }, "http://127.0.0.1:5174").origin).toBe(
      "http://127.0.0.1:5174",
    );
  }
});
it("requires explicit same-origin HTTPS for a session build", () => {
  for (const publicOrigin of [
    undefined,
    "http://workspace.test",
    "https://other.test",
    "https://workspace.test/path",
    "https://user@workspace.test",
  ])
    expect(() =>
      apiConfig({ mode: "session", publicOrigin }, "https://workspace.test"),
    ).toThrow();
  expect(() =>
    apiConfig(
      {
        mode: "session",
        publicOrigin: "https://workspace.test",
        localOrigin: "http://127.0.0.1:8128",
      },
      "https://workspace.test",
    ),
  ).toThrow("local override");
});
it("starts session builds read-only, independent of arbitrary truthy values", () => {
  const env = { mode: "session", publicOrigin: "https://workspace.test" };
  for (const sessionWrites of [undefined, "1", "true", "yes", "disabled"])
    expect(
      apiConfig({ ...env, sessionWrites }, "https://workspace.test").canWrite,
    ).toBe(false);
  expect(
    apiConfig({ ...env, sessionWrites: "enabled" }, "https://workspace.test")
      .canWrite,
  ).toBe(true);
});
