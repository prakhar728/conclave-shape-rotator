/**
 * Per-meeting retention override (Transcript Saving, Phase 2). Owner-only —
 * the meeting page mounts this only when MeetingView.is_owner is true.
 *
 * Lets the owner override the account-wide default for THIS meeting:
 *   - Use account default (clears the override → inherit /settings)
 *   - Keep forever
 *   - Auto-delete after N days
 *
 * The stored override is null (inherit) | 'keep_forever' | '<int>' days.
 */
"use client";

import { useState } from "react";

import { meetingOwner } from "@/lib/api";

type Selection = "inherit" | "keep_forever" | string; // string = day count

const PRESET_DAYS = [30, 90];

function overrideToSelection(override: string | null | undefined): Selection {
  if (override === null || override === undefined) return "inherit";
  if (override === "keep_forever") return "keep_forever";
  return override; // a day-count string
}

export function RetentionControl({
  sessionId,
  initialOverride,
  rawDeleted = false,
  bare = false,
}: {
  sessionId: string;
  initialOverride: string | null | undefined;
  rawDeleted?: boolean;
  // `bare` drops the outer card (the caller frames it, e.g. a popover).
  bare?: boolean;
}) {
  const [selection, setSelection] = useState<Selection>(
    overrideToSelection(initialOverride),
  );
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Day presets, plus the current value if it's an off-preset number.
  const dayOptions = Array.from(
    new Set([
      ...PRESET_DAYS.map(String),
      ...(/^\d+$/.test(selection) ? [selection] : []),
    ]),
  ).sort((a, b) => Number(a) - Number(b));

  async function save(next: Selection) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      if (next === "inherit") {
        await meetingOwner.setRetention(sessionId, { mode: "inherit" });
      } else if (next === "keep_forever") {
        await meetingOwner.setRetention(sessionId, { mode: "keep_forever" });
      } else {
        await meetingOwner.setRetention(sessionId, {
          mode: "days",
          days: Number(next),
        });
      }
      setSelection(next);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={bare ? "" : "mt-4 rounded-lg border border-border bg-card p-5"}>
      <h2 className="text-sm font-medium">Retention for this meeting</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Overrides your account default. Auto-delete removes only the raw
        transcript; the summary is kept.
      </p>
      {rawDeleted ? (
        <p className="mt-2 text-xs text-muted-foreground">
          This meeting&rsquo;s transcript has already been auto-deleted.
        </p>
      ) : null}

      <div className="mt-4 flex items-center gap-3">
        <select
          value={selection}
          onChange={(e) => {
            setSaved(false);
            save(e.target.value as Selection);
          }}
          disabled={busy}
          aria-label="Retention for this meeting"
          className="h-9 rounded-none border border-border bg-background px-2 text-xs text-foreground"
        >
          <option value="inherit">Use account default</option>
          <option value="keep_forever">Keep forever</option>
          {dayOptions.map((d) => (
            <option key={d} value={d}>
              Auto-delete after {d} days
            </option>
          ))}
        </select>
        {busy ? (
          <span className="text-xs text-muted-foreground">Saving…</span>
        ) : saved ? (
          <span className="text-xs text-muted-foreground">Saved.</span>
        ) : null}
        {error ? <span className="text-xs text-destructive">{error}</span> : null}
      </div>
    </section>
  );
}
