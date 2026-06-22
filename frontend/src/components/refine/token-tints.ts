/**
 * Token-state tints for the refine editor (mirrors lib/entity-tints).
 * The `tok-<state>` marker class is stable for tests; the color classes are
 * the visual. known = confirmed (green), candidate = recognized-but-unconfirmed
 * (blue), oov = novel/needs-review (amber).
 */
export const TOKEN_TINT: Record<string, string> = {
  known: "tok-known bg-signal-positive/15 text-signal-positive",
  candidate: "tok-candidate bg-signal-entity/15 text-signal-entity",
  oov: "tok-oov bg-amber-100 text-amber-800",
};

export function tokenTint(state: string | null | undefined): string {
  return (state && TOKEN_TINT[state]) || "";
}
