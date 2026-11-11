import { expect, it } from "vitest";
import {
  isRecipe,
  portalDraftKey,
  readPortalDraft,
  recipeHref,
  storePortalDraft,
  workshopBase,
} from "../src/workspace/portal-handoff";
function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => {
      values.set(k, v);
    },
    removeItem: (k: string) => {
      values.delete(k);
    },
  };
}
it("uses same-origin directory paths and recipe identifiers only", () => {
  expect(workshopBase("/workshop/")).toBe("/workshop/");
  expect(recipeHref("/workshop/", "decision")).toBe(
    "/workshop/workbench/fanout?recipe=decision",
  );
  for (const p of [
    "//evil.example/",
    "https://evil.example/",
    "/../",
    "/workshop?token=bad",
    "/workshop",
  ])
    expect(() => workshopBase(p)).toThrow();
  expect(isRecipe("notion")).toBe(false);
});
it("hands off a bounded private draft without putting its content in the URL", () => {
  const s = storage(),
    now = 100000;
  expect(storePortalDraft(s, "paper", "  a private note  ", now)).toBe(true);
  expect(readPortalDraft(s, now + 1)?.input).toBe("a private note");
  expect(recipeHref("/workshop/", "paper")).not.toContain("private");
  expect(readPortalDraft(s, now + 31 * 60 * 1000)).toBeNull();
  expect(s.getItem(portalDraftKey)).toBeNull();
});
it("rejects invalid or unavailable storage and never executes a task", () => {
  const s = storage();
  s.setItem(
    portalDraftKey,
    JSON.stringify({
      version: 1,
      recipe: "shell",
      input: "untrusted",
      createdAt: 1,
    }),
  );
  expect(readPortalDraft(s, 2)).toBeNull();
  expect(storePortalDraft(s, "paper", " ")).toBe(false);
  expect(storePortalDraft(s, "paper", "x".repeat(4001))).toBe(false);
  expect(
    storePortalDraft(
      {
        setItem: () => {
          throw Error("blocked");
        },
      },
      "paper",
      "note",
    ),
  ).toBe(false);
  s.setItem(portalDraftKey, "{");
  expect(readPortalDraft(s)).toBeNull();
});
