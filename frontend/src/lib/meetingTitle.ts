/**
 * The display heading for a meeting (Task #40).
 *
 * Prefer the server-provided `title` (an owner rename or the LLM-generated one).
 * Legacy meetings enriched before titles existed have `title == null` → fall back
 * to the first line/sentence of the summary (trimmed), matching the old behavior.
 * When there's nothing at all, return a neutral placeholder so a heading is never
 * blank.
 */
const FALLBACK = "Untitled meeting";

/** First line or first sentence of the summary, trimmed for use as a heading. */
function summaryLead(summary: string, maxChars = 80): string {
  const firstLine = summary.split(/\n/)[0]?.trim() ?? "";
  const base = firstLine || summary.trim();
  // Prefer a sentence boundary if it lands before the char cap — a complete
  // sentence reads as a title with no ellipsis needed.
  const period = base.indexOf(". ");
  if (period > 0 && period < maxChars) return base.slice(0, period);
  if (base.length <= maxChars) return base;
  // Hard truncation at the char cap → mark it with an ellipsis.
  return `${base.slice(0, maxChars).trimEnd()}…`;
}

export function meetingTitle(
  title?: string | null,
  summary?: string | null,
): string {
  const t = (title ?? "").trim();
  if (t) return t;
  const s = (summary ?? "").trim();
  if (s) return summaryLead(s);
  return FALLBACK;
}
