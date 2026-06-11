/**
 * One tint per entity CATEGORY (person / tech / affiliation — the OI-7 derived
 * 3-category model). Shares the graph's signal color language so the whole app
 * speaks one entity color vocabulary. All classes resolve to theme tokens.
 * (The backend still stores the fine 5-value `type`; the UI groups by category.)
 */
export const ENTITY_TINT: Record<string, string> = {
  person: "border-signal-speaker/40 bg-signal-speaker/10 text-signal-speaker",
  tech: "border-signal-positive/40 bg-signal-positive/10 text-signal-positive",
  affiliation: "border-signal-meeting/50 bg-signal-meeting/10 text-foreground",
};

export const ENTITY_TINT_FALLBACK = "border-border text-muted-foreground";

export function entityTint(category: string | null | undefined): string {
  return (category && ENTITY_TINT[category]) || ENTITY_TINT_FALLBACK;
}
