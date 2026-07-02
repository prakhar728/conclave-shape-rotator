/**
 * A meeting's processing lifecycle for dashboard card routing (Task #42).
 *
 * The backend derives `enrichment_state` ("processing" | "failed" | "done") with
 * a staleness cutoff, so a cancelled/empty/failed meeting no longer spins a
 * "Sharpening insights…" card forever. This prefers that field and falls back to
 * the legacy `is_processing` bool for any response that predates it.
 */
import type { Meeting } from "@/lib/api";

export type MeetingLifecycle = "processing" | "failed" | "done";

export function lifecycleOf(m: Meeting): MeetingLifecycle {
  if (m.enrichment_state === "processing" || m.enrichment_state === "failed") {
    return m.enrichment_state;
  }
  if (m.enrichment_state === "done") return "done";
  // Legacy response without enrichment_state → the old boolean.
  return m.is_processing ? "processing" : "done";
}
