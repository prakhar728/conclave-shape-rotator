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
 * P4: when `canTag` (the owner) and a `workspaceId` are present, each speaker
 * label is clickable → a small (name + email) form that tags that speaker via
 * FPM. A self-tag / dev-flag tag confirms instantly and the name flips in place
 * across every line that speaker said; tagging someone else shows a "pending"
 * badge until they confirm on their consent dashboard.
 *
 * Mount only when MeetingView.can_view_transcript is defined (workspace-mode
 * / demo sessions); legacy cohort sessions never expose a transcript.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { SpeakerTagForm } from "@/components/speaker-tag-form";
import { ApiError, meetings as meetingsApi, type TranscriptSegment } from "@/lib/api";
import { speakerLabel } from "@/lib/speakerLabel";
import { groupIntoTurns } from "@/lib/turns";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; segments: TranscriptSegment[] }
  | { kind: "auto_deleted" }
  | { kind: "error"; message: string };

export function TranscriptPanel({
  sessionId,
  canView,
  workspaceId = null,
  canTag = false,
  reloadKey = 0,
  onSeek,
  activeSegmentIndex = null,
}: {
  sessionId: string;
  canView: boolean;
  workspaceId?: string | null;
  canTag?: boolean;
  // Bump to force a re-fetch — the meeting page increments this while post-processing so the diart
  // preview swaps to DiariZen's authoritative transcript (+ names) when the background finalize lands.
  reloadKey?: number;
  // Task #41 — when set (audio available), clicking a segment's text seeks the
  // meeting audio player to that segment's start and plays. Undefined = no audio,
  // segments are not seek-clickable (no dead affordance).
  onSeek?: (seconds: number) => void;
  // Playhead-follows-text: index of the segment currently under the playhead.
  activeSegmentIndex?: number | null;
}) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  // Task #3 — name to pre-fill the tag form with when it's opened via the
  // "Proposed:" Confirm/Edit affordance (blank for a plain label click).
  const [formName, setFormName] = useState("");
  // label -> proposed name, for speakers whose tag is awaiting the target's confirm
  const [pending, setPending] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Open the tag form on a segment, optionally pre-filling the name (Confirm/Edit
  // of a recognized-but-unconsented proposal); toggles closed if already open.
  const openForm = useCallback((idx: number, name = "") => {
    setFormName(name);
    // Confirm/Edit (a name is supplied) always opens; a bare label click toggles.
    setOpenIdx((cur) => (name === "" && cur === idx ? null : idx));
  }, []);

  const load = useCallback(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    meetingsApi
      .transcript(sessionId)
      .then((r) => {
        if (!cancelled) setState({ kind: "ready", segments: r.segments });
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 410) {
          setState({ kind: "auto_deleted" });
          return;
        }
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : "Failed to load transcript",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!canView) return;
    return load();
  }, [canView, load, reloadKey]);

  const taggable = Boolean(canTag && workspaceId);

  async function submitTag(label: string, name: string, email: string) {
    if (!workspaceId) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await meetingsApi.tagSpeaker(workspaceId, sessionId, {
        label,
        name,
        email,
      });
      setOpenIdx(null);
      if (res.status === "confirmed") {
        setPending((p) => {
          const next = { ...p };
          delete next[label];
          return next;
        });
        load(); // names flip in place across the whole transcript
      } else {
        setPending((p) => ({ ...p, [label]: name })); // awaiting confirm
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Tag failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8">
      <h2 className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
        Transcript
      </h2>
      <Body
        sessionId={sessionId}
        state={state}
        canView={canView}
        taggable={taggable}
        pending={pending}
        openIdx={openIdx}
        setOpenIdx={setOpenIdx}
        openForm={openForm}
        formName={formName}
        submitTag={submitTag}
        busy={busy}
        err={err}
        onSeek={onSeek}
        activeSegmentIndex={activeSegmentIndex}
      />
    </section>
  );
}

function Body({
  sessionId,
  state,
  canView,
  taggable,
  pending,
  openIdx,
  setOpenIdx,
  openForm,
  formName,
  submitTag,
  busy,
  err,
  onSeek,
  activeSegmentIndex,
}: {
  sessionId: string;
  state: LoadState;
  canView: boolean;
  taggable: boolean;
  pending: Record<string, string>;
  openIdx: number | null;
  setOpenIdx: (i: number | null) => void;
  openForm: (idx: number, name?: string) => void;
  formName: string;
  submitTag: (label: string, name: string, email: string) => void;
  busy: boolean;
  err: string | null;
  onSeek?: (seconds: number) => void;
  activeSegmentIndex?: number | null;
}) {
  // Playhead-follows-text: scroll the active segment into view as audio plays.
  const segRefs = useRef<Map<number, HTMLLIElement>>(new Map());
  useEffect(() => {
    if (activeSegmentIndex == null) return;
    segRefs.current
      .get(activeSegmentIndex)
      ?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [activeSegmentIndex]);

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
  // Task #37 — coalesce consecutive same-speaker spans into turns (shared util,
  // mirrors the server projection). Edit/clip/seek still target the turn's spans.
  const turns = groupIntoTurns(state.segments);
  // Cumulative first-span index per turn (to map the playhead's active span → turn).
  const turnSpanStart: number[] = [];
  turns.forEach((t, i) => {
    turnSpanStart.push(i === 0 ? 0 : turnSpanStart[i - 1] + turns[i - 1].spans.length);
  });
  return (
    <ol className="flex flex-col gap-5">
      {turns.map((turn, turnIdx) => {
        const firstSpan = turnSpanStart[turnIdx];
        const lastSpan = firstSpan + turn.spans.length; // exclusive
        const pendingName = pending[turn.speaker as string];
        // Normalize the raw diarizer label to "Speaker N" when there's no name.
        const display = turn.speaker_name ?? speakerLabel(turn.speaker);
        const proposedName =
          !turn.speaker_name && !pendingName ? turn.proposed_name ?? null : null;
        // The playhead's active span falls inside this turn's span range.
        const isActive =
          activeSegmentIndex != null &&
          activeSegmentIndex >= firstSpan &&
          activeSegmentIndex < lastSpan;
        return (
          <li
            key={turnIdx}
            ref={(el) => {
              if (el) segRefs.current.set(turnIdx, el);
              else segRefs.current.delete(turnIdx);
            }}
            data-active={isActive || undefined}
            className={`-mx-2 rounded-md px-2 transition-colors ${
              isActive ? "bg-accent/40" : ""
            }`}
          >
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              {taggable ? (
                <button
                  type="button"
                  onClick={() => openForm(turnIdx)}
                  className="text-sm font-semibold text-foreground underline decoration-dotted decoration-muted-foreground/40 underline-offset-2 transition-colors hover:decoration-foreground"
                  title="Tag this speaker"
                >
                  {display}
                </button>
              ) : (
                <span className="text-sm font-semibold text-foreground">{display}</span>
              )}
              {taggable && proposedName ? (
                <span
                  data-testid="proposed-chip"
                  className="inline-flex items-center gap-1.5 rounded-md border border-signal-entity/50 px-2 py-0.5 text-[0.7rem] text-signal-entity"
                >
                  Proposed: {proposedName}
                  <button
                    type="button"
                    onClick={() => openForm(turnIdx, proposedName)}
                    className="font-semibold underline decoration-dotted underline-offset-2 hover:text-foreground"
                  >
                    Confirm
                  </button>
                  <button
                    type="button"
                    onClick={() => openForm(turnIdx, proposedName)}
                    className="underline decoration-dotted underline-offset-2 hover:text-foreground"
                  >
                    Edit
                  </button>
                </span>
              ) : null}
              {pendingName ? (
                <span className="rounded-md border border-signal-warn/50 px-2 py-0.5 text-[0.7rem] text-signal-warn">
                  pending: {pendingName}
                </span>
              ) : null}
              {turn.start != null ? (
                <span className="font-mono text-xs text-muted-foreground/50">
                  {formatTime(turn.start)}
                </span>
              ) : null}
            </div>
            {taggable && openIdx === turnIdx ? (
              <SpeakerTagForm
                key={formName}
                label={turn.speaker as string}
                busy={busy}
                err={err}
                initialName={formName}
                onCancel={() => setOpenIdx(null)}
                onSubmit={submitTag}
              />
            ) : null}
            {onSeek && turn.start != null ? (
              <p
                data-testid="seek-segment"
                role="button"
                tabIndex={0}
                title="Jump the audio to here"
                onClick={() => {
                  if (window.getSelection()?.toString()) return;
                  onSeek(turn.start as number);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSeek(turn.start as number);
                  }
                }}
                className="mt-0.5 cursor-pointer whitespace-pre-line rounded-sm text-sm leading-relaxed text-foreground/90 transition-colors hover:text-foreground"
              >
                {turn.text}
              </p>
            ) : (
              <p className="mt-0.5 whitespace-pre-line text-sm leading-relaxed text-foreground/90">
                {turn.text}
              </p>
            )}
            {turn.start != null && turn.end != null ? (
              <AudioSegmentPlayer sessionId={sessionId} start={turn.start} end={turn.end} />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Per-segment clip player (Task #30). Lazily reveals an <audio> element pointed at the
 * decrypt-on-read `?start=&end=` clip endpoint — preload="none" so nothing is fetched
 * until the user plays. Cookie auth is same-origin. This is the component #3 reuses in
 * the "Is this you?" box. Only rendered when the segment has a start AND end time.
 */
function AudioSegmentPlayer({
  sessionId,
  start,
  end,
}: {
  sessionId: string;
  start: number;
  end: number;
}) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 inline-flex items-center gap-1 text-[0.7rem] text-muted-foreground transition hover:text-foreground"
        title="Play this segment"
      >
        ▶ Play clip
      </button>
    );
  }
  return (
    <audio
      controls
      autoPlay
      preload="none"
      src={meetingsApi.audioUrl(sessionId, { start, end })}
      className="mt-2 h-8 w-full max-w-xs"
    >
      Your browser does not support audio playback.
    </audio>
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
          : "rounded-none border border-dashed border-border p-4 text-xs text-muted-foreground"
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
