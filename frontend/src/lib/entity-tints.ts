/**
 * One tint per entity type — shares the graph's signal color language
 * (UI-NOW.md §3: person=speaker amber, topic=entity sky) so the whole app
 * speaks one entity color vocabulary. All classes resolve to theme tokens.
 */
export const ENTITY_TINT: Record<string, string> = {
  person: "border-signal-speaker/40 bg-signal-speaker/10 text-signal-speaker",
  project: "border-primary/40 bg-primary/10 text-primary",
  topic: "border-signal-entity/40 bg-signal-entity/10 text-signal-entity",
  company: "border-signal-meeting/50 bg-signal-meeting/10 text-foreground",
  tool: "border-signal-positive/40 bg-signal-positive/10 text-signal-positive",
};

export const ENTITY_TINT_FALLBACK = "border-border text-muted-foreground";

export function entityTint(type: string | null | undefined): string {
  return (type && ENTITY_TINT[type]) || ENTITY_TINT_FALLBACK;
}
