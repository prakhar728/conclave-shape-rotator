/**
 * Transcript panel on the meeting detail page (Transcript Saving feature).
 *
 * The raw transcript is a gated surface: the backend's
 * GET /transcripts/sessions/{id}/transcript only serves it to the owner,
 * full workspace members, and 'summary_and_transcript' recipients.
 *
 * This component renders one of four states:
 *   - canView=false        → "not shared with you" (summary-only recipient)
 *   - 410 from the fetch   → "auto-deleted" (Phase 2 retention purge)
 *   - empty/normal segments→ the transcript
 *   - other error          → a generic failure line
 *
 * Mount only when MeetingView.can_view_transcript is defined (workspace-mode
 * / demo sessions); legacy cohort sessions never expose a transcript.
 */
"use client";

import { useEffect, useState } from "react";

import { ApiError, meetings as meetingsApi, type TranscriptSegment } from "@/lib/api";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; segments: TranscriptSegment[] }
  | { kind: "auto_deleted" }
  | { kind: "error"; message: string };

export function TranscriptPanel({
  sessionId,
  canView,
}: {
  sessionId: string;
  canView: boolean;
}) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (!canView) return;
    let cancelled = false;
    meetingsApi
      .transcript(sessionId)
      .then((r) => {
        if (!cancelled) setState({ kind: "ready", segments: r.segments });
      })
      .catch((err) => {
        if (cancelled) return;
        // 410 Gone is the Phase 2 retention signal: raw transcript purged,
        // summary kept. Handled now so retention ships without touching this.
        if (err instanceof ApiError && err.status === 410) {
          setState({ kind: "auto_deleted" });
          return;
        }
        setState({
          kind: "error",
          message:
            err instanceof Error ? err.message : "Failed to load transcript",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, canView]);

  return (
    <section className="mt-8">
      <h2 className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
        Transcript
      </h2>
      <Body state={state} canView={canView} />
    </section>
  );
}

function Body({ state, canView }: { state: LoadState; canView: boolean }) {
  if (!canView) {
    return (
      <Note>
        The full transcript wasn&rsquo;t shared with you — you&rsquo;re seeing
        the summary above.
      </Note>
    );
  }
  if (state.kind === "loading") {
    return <Note>Loading transcript…</Note>;
  }
  if (state.kind === "auto_deleted") {
    return (
      <Note>
        The raw transcript was auto-deleted under the owner&rsquo;s retention
        settings. The summary above is kept.
      </Note>
    );
  }
  if (state.kind === "error") {
    return <Note tone="error">{state.message}</Note>;
  }
  if (state.segments.length === 0) {
    return <Note>No transcript text was captured for this meeting.</Note>;
  }
  return (
    <ol className="flex flex-col gap-3">
      {state.segments.map((seg, idx) => (
        <li
          key={idx}
          className="rounded-xl border border-border bg-card p-4 shadow-sm"
        >
          <p className="text-xs font-medium text-muted-foreground">
            {seg.speaker_name ?? seg.speaker}
            {seg.start != null ? (
              <span className="ml-2 font-mono text-[0.7rem] opacity-70">
                {formatTime(seg.start)}
              </span>
            ) : null}
          </p>
          <p className="mt-1 text-sm leading-relaxed">{seg.text}</p>
        </li>
      ))}
    </ol>
  );
}

function Note({
  children,
  tone = "muted",
}: {
  children: React.ReactNode;
  tone?: "muted" | "error";
}) {
  return (
    <p
      className={
        tone === "error"
          ? "text-xs text-destructive"
          : "rounded-lg border border-dashed border-border p-4 text-xs text-muted-foreground"
      }
    >
      {children}
    </p>
  );
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
