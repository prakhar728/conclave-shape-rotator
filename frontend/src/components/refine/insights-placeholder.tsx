/**
 * Shown on the meeting page when there are no insights, explaining WHY (so an empty
 * page doesn't read as broken). Driven by MeetingView.enrichment_status.
 */
const MESSAGES: Record<string, string> = {
  skipped:
    "Insights unavailable — no LLM is configured (set CONCLAVE_LLM_BACKEND). The transcript is fully editable in Refine.",
  failed: "Insights couldn't be generated — the LLM was unreachable. Try again later.",
  pending: "Insights are still being generated…",
};

export function InsightsPlaceholder({ status }: { status?: string }) {
  const msg =
    (status && MESSAGES[status]) ??
    "No action items, questions, or insights were found in this meeting.";
  return (
    <section className="mb-8" data-testid="insights-placeholder">
      <div className="rounded-none border border-dashed border-border bg-card p-4">
        <p className="text-xs text-muted-foreground">{msg}</p>
      </div>
    </section>
  );
}
