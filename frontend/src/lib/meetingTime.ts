/**
 * Format a meeting's capture time for display (Task #39).
 *
 * The backend stamps a full UTC ISO `created_at` at ingest (e.g.
 * "2026-07-02T14:23:01.5Z"); `date` is only date-granular. We store UTC and
 * render in the viewer's local timezone. Recent meetings read relative
 * ("2h ago"), older ones read absolute ("Jul 2, 2026, 3:14 PM"). Legacy
 * sessions with no `created_at` degrade to the plain date — never a bogus time.
 */

export type MeetingWhen = {
  /** Short label for inline display (relative for recent, absolute otherwise). */
  label: string;
  /** Full absolute local timestamp, always — used as a hover title. */
  title: string;
  /** True when we have a real clock time (a `created_at`); false = date-only. */
  hasTime: boolean;
};

const RECENT_MS = 24 * 60 * 60 * 1000; // within a day → relative

function absolute(d: Date): string {
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function relative(deltaMs: number): string {
  const mins = Math.floor(deltaMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ago`;
}

/**
 * @param createdAt full UTC ISO timestamp, or null/undefined for legacy sessions
 * @param fallbackDate the date-granular `date` shown when there's no timestamp
 * @param now injected for deterministic tests; defaults to the current time
 */
export function meetingWhen(
  createdAt?: string | null,
  fallbackDate?: string | null,
  now: Date = new Date(),
): MeetingWhen {
  if (createdAt) {
    const d = new Date(createdAt);
    if (!Number.isNaN(d.getTime())) {
      const delta = now.getTime() - d.getTime();
      const abs = absolute(d);
      // Future timestamps (clock skew) or older-than-a-day → absolute.
      const label = delta >= 0 && delta < RECENT_MS ? relative(delta) : abs;
      return { label, title: abs, hasTime: true };
    }
  }
  const dateLabel = (fallbackDate ?? "").trim();
  return { label: dateLabel, title: dateLabel, hasTime: false };
}
