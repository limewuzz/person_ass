export const portalDraftKey = "mw.portal.handoff.v1";
export const recipeIds = ["paper", "decision", "wechat", "checkpoint"] as const;
export type RecipeId = (typeof recipeIds)[number];
export interface PortalDraft {
  version: 1;
  recipe: RecipeId;
  input: string;
  createdAt: number;
}
export function isRecipe(value: unknown): value is RecipeId {
  return (
    typeof value === "string" &&
    (recipeIds as readonly string[]).includes(value)
  );
}
export function workshopBase(value: string): string {
  if (!/^\/(?:[A-Za-z0-9_-]+\/)*$/.test(value))
    throw Error("Invalid workshop path");
  return value;
}
export function recipeHref(base: string, recipe: RecipeId) {
  return `${workshopBase(base)}workbench/fanout?recipe=${recipe}`;
}
export function storePortalDraft(
  storage: Pick<Storage, "setItem">,
  recipe: RecipeId,
  input: string,
  now = Date.now(),
): boolean {
  const trimmed = input.trim();
  if (!isRecipe(recipe) || !trimmed || trimmed.length > 4000) return false;
  try {
    storage.setItem(
      portalDraftKey,
      JSON.stringify({
        version: 1,
        recipe,
        input: trimmed,
        createdAt: now,
      } satisfies PortalDraft),
    );
    return true;
  } catch {
    return false;
  }
}
export function readPortalDraft(
  storage: Pick<Storage, "getItem" | "removeItem">,
  now = Date.now(),
): PortalDraft | null {
  try {
    const d: unknown = JSON.parse(storage.getItem(portalDraftKey) ?? "null");
    if (
      d &&
      typeof d === "object" &&
      "version" in d &&
      d.version === 1 &&
      "recipe" in d &&
      isRecipe(d.recipe) &&
      "input" in d &&
      typeof d.input === "string" &&
      d.input.trim().length > 0 &&
      d.input.length <= 4000 &&
      "createdAt" in d &&
      typeof d.createdAt === "number" &&
      d.createdAt <= now &&
      now - d.createdAt <= 30 * 60 * 1000
    )
      return d as PortalDraft;
    storage.removeItem(portalDraftKey);
  } catch {
    /* Invalid or unavailable browser storage does not trigger any action. */
  }
  return null;
}
