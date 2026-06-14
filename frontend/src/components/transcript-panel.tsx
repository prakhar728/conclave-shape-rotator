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

import { useCallback, useEffect, useState } from "react";

import { ApiError, meetings as meetingsApi, type TranscriptSegment } from "@/lib/api";

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
}: {
  sessionId: string;
  canView: boolean;
  workspaceId?: string | null;
  canTag?: boolean;
}) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [openIdx, setOpenIdx] = useState<number | null>(null);
  // label -> proposed name, for speakers whose tag is awaiting the target's confirm
  const [pending, setPending] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

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
  }, [canView, load]);

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
        state={state}
        canView={canView}
        taggable={taggable}
        pending={pending}
        openIdx={openIdx}
        setOpenIdx={setOpenIdx}
        submitTag={submitTag}
        busy={busy}
        err={err}
      />
    </section>
  );
}

function Body({
  state,
  canView,
  taggable,
  pending,
  openIdx,
  setOpenIdx,
  submitTag,
  busy,
  err,
}: {
  state: LoadState;
  canView: boolean;
  taggable: boolean;
  pending: Record<string, string>;
  openIdx: number | null;
  setOpenIdx: (i: number | null) => void;
  submitTag: (label: string, name: string, email: string) => void;
  busy: boolean;
  err: string | null;
}) {
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
      {state.segments.map((seg, idx) => {
        const pendingName = pending[seg.speaker];
        const display = seg.speaker_name ?? seg.speaker;
        return (
          <li
            key={idx}
            className="rounded-xl border border-border bg-card p-4 shadow-sm"
          >
            <p className="text-xs font-medium text-muted-foreground">
              {taggable ? (
                <button
                  type="button"
                  onClick={() => setOpenIdx(openIdx === idx ? null : idx)}
                  className="underline decoration-dotted underline-offset-2 hover:text-foreground"
                  title="Tag this speaker"
                >
                  {display}
                </button>
              ) : (
                display
              )}
              {pendingName ? (
                <span className="ml-2 rounded-full border border-amber-500/60 px-2 py-0.5 text-[0.65rem] text-amber-600">
                  pending: {pendingName}
                </span>
              ) : null}
              {seg.start != null ? (
                <span className="ml-2 font-mono text-[0.7rem] opacity-70">
                  {formatTime(seg.start)}
                </span>
              ) : null}
            </p>
            {taggable && openIdx === idx ? (
              <TagForm
                label={seg.speaker}
                busy={busy}
                err={err}
                onCancel={() => setOpenIdx(null)}
                onSubmit={submitTag}
              />
            ) : null}
            <p className="mt-1 text-sm leading-relaxed">{seg.text}</p>
          </li>
        );
      })}
    </ol>
  );
}

function TagForm({
  label,
  busy,
  err,
  onCancel,
  onSubmit,
}: {
  label: string;
  busy: boolean;
  err: string | null;
  onCancel: () => void;
  onSubmit: (label: string, name: string, email: string) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const ready = name.trim() !== "" && email.trim() !== "";
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-border p-2">
      <span className="text-[0.7rem] uppercase tracking-wide text-muted-foreground">
        Who is {label}?
      </span>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Full name"
        className="rounded border border-border bg-background px-2 py-1 text-xs"
      />
      <input
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="email@company.com"
        className="rounded border border-border bg-background px-2 py-1 text-xs"
      />
      <button
        type="button"
        disabled={!ready || busy}
        onClick={() => onSubmit(label, name.trim(), email.trim())}
        className="rounded bg-foreground px-3 py-1 text-xs font-semibold text-background disabled:opacity-40"
      >
        {busy ? "Tagging…" : "Tag"}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="rounded border border-border px-3 py-1 text-xs"
      >
        Cancel
      </button>
      {err ? <span className="text-[0.7rem] text-destructive">{err}</span> : null}
    </div>
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
