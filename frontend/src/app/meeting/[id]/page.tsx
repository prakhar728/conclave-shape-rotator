/**
 * /meeting/[id] — single-meeting detail card.
 *
 * Calls the existing /transcripts/sessions/{id} endpoint (renamed via
 * next.config rewrite to /api/transcripts/...). Permission enforcement
 * lives server-side in 1.7's can_user_see + 1.14's dual-mode get_session.
 *
 * Renders:
 *  - Header (workspace context)
 *  - Title (summary or fallback)
 *  - Action items
 *  - Open questions
 *  - Insights
 *  - Entities (small)
 *  - Transcript (gated — TranscriptPanel fetches the raw transcript only
 *    when can_view_transcript is true; otherwise shows a state message)
 */
"use client";

import { ArrowLeft, Check, Clock, Copy, Share2, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { MeetingTitleHeading } from "@/components/meeting-title";
import { OriginBadge } from "@/components/origin-badge";
import { OwnerControls } from "@/components/owner-controls";
import {
  MeetingAudioPlayer,
  type MeetingAudioPlayerHandle,
} from "@/components/meeting-audio-player";
import { PageError, PageLoading } from "@/components/page-state";
import { ContributeShapeOS } from "@/components/refine/contribute-shapeos";
import { InsightsPlaceholder } from "@/components/refine/insights-placeholder";
import { RefineActions } from "@/components/refine/refine-actions";
import { RefineEditor } from "@/components/refine/refine-editor";
import { useRefineDraft } from "@/components/refine/use-refine-draft";
import { RetentionControl } from "@/components/retention-control";
import { TranscriptPanel } from "@/components/transcript-panel";
import { meetingWhen } from "@/lib/meetingTime";
import { cn } from "@/lib/utils";
import {
  ApiError,
  auth,
  meetings as meetingsApi,
  refine,
  type MeResponse,
  type MeetingView,
  type Signal,
  type TranscriptSegment,
} from "@/lib/api";

export default function MeetingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [meeting, setMeeting] = useState<MeetingView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const { draft, setDraft, preparing } = useRefineDraft(id);
  // True while a post-approve re-derive is running (insights regenerating in the bg).
  const [regenerating, setRegenerating] = useState(false);
  // Transcript segments — powers the header's duration + copy-to-clipboard, and
  // (Task #41) resolves an editor segment_id → its raw start time for seeking.
  const [segments, setSegments] = useState<TranscriptSegment[] | null>(null);
  const [copied, setCopied] = useState(false);
  // Task #41 — imperative handle on the audio player + whether audio is actually
  // playable, so transcript segments become seek-clickable only when useful.
  const playerRef = useRef<MeetingAudioPlayerHandle>(null);
  const [audioReady, setAudioReady] = useState(false);
  const seekTo = useCallback((seconds: number) => {
    playerRef.current?.seekTo(seconds);
  }, []);
  // Task #42 — owner hard-delete this meeting, then return to the dashboard.
  const [deleting, setDeleting] = useState(false);
  async function handleDelete() {
    if (!window.confirm("Delete this meeting? This can't be undone.")) return;
    setDeleting(true);
    try {
      await meetingsApi.delete(id);
      router.push("/dashboard");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
      setDeleting(false);
    }
  }
  // Which sub-tab is shown: the summary/insights or the transcript.
  const [tab, setTab] = useState<"summary" | "transcript">("summary");

  // A freshly-recorded in-person meeting lands here while the background finalize runs (DiariZen
  // authoritative re-diarization → VFTE names → enrichment). The diart transcript is shown immediately;
  // we poll until the summary appears (the backend's own `is_processing = not summary` signal) and bump
  // `reloadKey` so the TranscriptPanel re-fetches — swapping diart for the authoritative transcript.
  const processing = Boolean(meeting && !meeting.summary);
  useEffect(() => {
    if (!processing) return;
    let n = 0;
    const iv = setInterval(async () => {
      n += 1;
      try {
        const m = await meetingsApi.get(id);
        setMeeting(m);
        setReloadKey((k) => k + 1);
        if (m.summary || n >= 45) clearInterval(iv); // stop when enriched, or after ~3 min
      } catch {
        if (n >= 45) clearInterval(iv);
      }
    }, 4000);
    return () => clearInterval(iv);
  }, [processing, id]);

  // While insights regenerate in the background — either #9's post-approve
  // re-derive (signalled by the draft's `insights_stale`) or #13's heal-on-open
  // after a deferred speaker-name confirm (signalled by the meeting's
  // `insights_regenerating`, a stamp-derived flag that flips false the moment the
  // re-enrich re-stamps) — keep the "Updating insights" badge up and poll both
  // signals. Clearing on BOTH (not just the draft) is what stops the badge
  // lingering for meetings whose draft is absent/already-settled at heal time:
  // `getDraft` may 404 (no v2) or already read `insights_stale=false`, in which
  // case `insights_regenerating` is the authoritative done-signal.
  useEffect(() => {
    if (!regenerating) return;
    let n = 0;
    const iv = setInterval(async () => {
      n += 1;
      try {
        const [m, d] = await Promise.all([
          meetingsApi.get(id),
          refine.getDraft(id).catch(() => null), // 404 / no v2 → treat as "not re-deriving"
        ]);
        setMeeting(m);
        if (d) setDraft(d);
        const healing = m.insights_regenerating === true; // #13 stamp divergence in flight
        const rederiving = d?.insights_stale === true; // #9 post-approve re-derive in flight
        if ((!healing && !rederiving) || n >= 45) {
          clearInterval(iv);
          setRegenerating(false);
        }
      } catch {
        if (n >= 45) {
          clearInterval(iv);
          setRegenerating(false);
        }
      }
    }, 4000);
    return () => clearInterval(iv);
  }, [regenerating, id, setDraft]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [meResp, mResp] = await Promise.all([
          auth.me(),
          meetingsApi.get(id),
        ]);
        if (cancelled) return;
        setMe(meResp);
        setMeeting(mResp);
        // Task #13 — a deferred speaker-name confirm is healing this summary in the
        // background on open. Reuse #9's "Updating insights" flow: show the badge and
        // poll the draft until the re-enrich clears `insights_stale`.
        if (mResp.insights_regenerating) setRegenerating(true);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError) {
          if (err.status === 401) {
            router.push("/login");
            return;
          }
          if (err.status === 403) {
            setError("You don't have access to this meeting.");
            return;
          }
          if (err.status === 404) {
            setError("Meeting not found.");
            return;
          }
        }
        setError(err instanceof Error ? err.message : "Failed to load meeting");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, router]);

  // Pull the transcript once the viewer is allowed to see it — used for the
  // header's duration readout and the copy-to-clipboard button.
  const canViewTranscript = meeting?.can_view_transcript ?? false;
  useEffect(() => {
    if (!canViewTranscript) return;
    let cancelled = false;
    meetingsApi
      .transcript(id)
      .then((r) => !cancelled && setSegments(r.segments))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [canViewTranscript, id, reloadKey]);

  if (error) {
    return (
      <PageError message={error}>
        <Link
          href="/dashboard"
          className="mt-3 inline-block text-xs text-muted-foreground hover:text-foreground"
        >
          Back to dashboard
        </Link>
      </PageError>
    );
  }
  if (!me || !meeting) return <PageLoading />;

  const durationSec =
    segments && segments.length
      ? Math.max(0, ...segments.map((s) => s.end ?? 0))
      : 0;

  // Task #39 — capture time-of-day (relative for recent, absolute otherwise);
  // legacy sessions with no created_at degrade to the plain date.
  const when = meetingWhen(meeting.created_at, meeting.date);

  async function copyTranscript() {
    if (!segments?.length) return;
    const text = segments
      .map((s) => `${s.speaker_name ?? s.speaker}: ${s.text}`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard blocked (insecure context / permissions) — no-op
    }
  }

  return (
    <AppShell user={me.user}>
      <main className="mx-auto max-w-5xl px-6 py-10">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden />
          Back to dashboard
        </Link>

        <div className="mt-6 mb-8 border-b border-border pb-6">
          <div className="flex items-center justify-end gap-2">
              {canViewTranscript ? (
                <button
                  onClick={copyTranscript}
                  disabled={!segments?.length}
                  title="Copy transcript to clipboard"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-50"
                >
                  {copied ? (
                    <Check className="size-4" aria-hidden />
                  ) : (
                    <Copy className="size-4" aria-hidden />
                  )}
                  {copied ? "Copied" : "Copy transcript"}
                </button>
              ) : null}
              {meeting.is_owner ? (
                <>
                  <IconPopover icon={Share2} label="Sharing">
                    <OwnerControls
                      bare
                      sessionId={meeting.session_id}
                      initialVisibility={
                        (meeting.effective_visibility as "owner-only" | "shared") ??
                        "owner-only"
                      }
                      initialSharedToWorkspace={meeting.shared_to_workspace ?? false}
                      initialOwnerOnly={meeting.owner_only ?? false}
                    />
                  </IconPopover>
                  <IconPopover icon={Clock} label="Retention">
                    <RetentionControl
                      bare
                      sessionId={meeting.session_id}
                      initialOverride={meeting.retention_override}
                      rawDeleted={meeting.raw_transcript_deleted}
                    />
                  </IconPopover>
                  {/* Task #42 — owner hard-delete this meeting. */}
                  <button
                    type="button"
                    data-testid="delete-meeting"
                    onClick={handleDelete}
                    disabled={deleting}
                    aria-label="Delete meeting"
                    title="Delete meeting"
                    className="inline-flex size-8 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive disabled:opacity-50"
                  >
                    <Trash2 className="size-4" aria-hidden />
                  </button>
                </>
              ) : null}
          </div>
          <MeetingTitleHeading
            sessionId={meeting.session_id}
            title={meeting.title}
            summary={meeting.summary}
            isOwner={Boolean(meeting.is_owner)}
            onRenamed={(t) =>
              setMeeting((m) => (m ? { ...m, title: t } : m))
            }
          />

          <div className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
            <span title={when.title} data-testid="meeting-when">
              {when.label}
            </span>
            <span aria-hidden>·</span>
            <OriginBadge origin={meeting.origin} />
            {durationSec > 0 ? (
              <>
                <span aria-hidden>·</span>
                <span>{fmtDuration(durationSec)}</span>
              </>
            ) : null}
            {meeting.meeting_intent_version ? (
              <>
                <span aria-hidden>·</span>
                <span
                  data-testid="agenda-grounded"
                  title={`meeting_intent_version: ${meeting.meeting_intent_version}`}
                  className="inline-flex items-center gap-1.5 text-foreground"
                >
                  <span className="size-1.5 rounded-full bg-attested" aria-hidden />
                  Agenda-grounded
                </span>
              </>
            ) : null}
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground/60">
            {meeting.session_id}
          </p>
        </div>

        {processing ? (
          <div className="mb-8 flex items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3">
            <span className="size-2 animate-pulse rounded-full bg-primary" />
            <p className="text-sm text-muted-foreground">
              Post-processing. Showing the live diart transcript; the final
              re-diarized transcript, speaker names, and summary appear here when ready.
            </p>
          </div>
        ) : null}

        {regenerating ? (
          <div
            data-testid="insights-updating"
            className="mb-8 flex items-center gap-3 rounded-lg border border-signal-entity/30 bg-signal-entity/5 px-4 py-3"
          >
            <span className="size-2 animate-pulse rounded-full bg-signal-entity" />
            <p className="text-sm text-muted-foreground">
              Updating insights. Re-deriving the summary and signals with the latest speaker names…
            </p>
          </div>
        ) : null}

        {/* Sub-tabs: summary/insights vs the full transcript. */}
        <div className="mb-6 flex items-center gap-1 border-b border-border">
          {(["summary", "transcript"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "relative px-4 py-2 text-sm font-medium capitalize transition-colors",
                tab === t
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t}
              {tab === t ? (
                <span className="absolute inset-x-0 -bottom-px h-0.5 bg-foreground" aria-hidden />
              ) : null}
            </button>
          ))}
        </div>

        {tab === "summary" ? (
          <>
            {meeting.entities.length > 0 ? (
              <section className="mb-8">
                <h2 className="mb-2.5 text-sm font-semibold text-foreground">
                  Entities
                </h2>
                <ul className="flex flex-wrap gap-1.5">
                  {meeting.entities.map((e, idx) => (
                    <li key={`${e.name}-${idx}`}>
                      <Link
                        href={`/entity/${encodeURIComponent(e.name)}`}
                        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-0.5 text-xs transition-colors hover:bg-secondary"
                      >
                        <span className="text-foreground">{e.name}</span>
                        <span className="font-mono text-[10px] text-muted-foreground">
                          {e.type}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            <SignalGroup
              title="Action items"
              signals={meeting.signals_by_kind.action_items}
              accent="action"
            />
            <SignalGroup
              title="Open questions"
              signals={meeting.signals_by_kind.open_questions}
              accent="open_question"
            />
            <SignalGroup
              title="Insights"
              signals={meeting.signals_by_kind.insights}
              accent="insight"
            />

            {meeting.signals_by_kind.action_items.length === 0 &&
            meeting.signals_by_kind.open_questions.length === 0 &&
            meeting.signals_by_kind.insights.length === 0 ? (
              <InsightsPlaceholder status={meeting.enrichment_status} />
            ) : null}

          </>
        ) : meeting.can_view_transcript !== undefined ? (
          <div>
            {/* Task #30 — audio player; self-hides when no audio was stored. */}
            <div className="mb-6">
              <MeetingAudioPlayer
                ref={playerRef}
                sessionId={meeting.session_id}
                isOwner={Boolean(meeting.is_owner)}
                storeAudio={meeting.store_audio}
                onAvailabilityChange={setAudioReady}
              />
            </div>
            {meeting.is_owner && draft && !preparing ? (
              <>
                <RefineEditor
                  draft={draft}
                  sessionId={id}
                  workspaceId={meeting.workspace_id ?? null}
                  canTag={Boolean(meeting.is_owner)}
                  resolvedSpeakers={meeting.resolved_speakers}
                  onDraftChange={(d) => {
                    setDraft(d);
                  }}
                  // Task #41 — seek from a segment's speaker row. The editor is
                  // token-based (no per-segment start), so resolve segment_id →
                  // the raw segment's start here (segment_id mirrors raw index).
                  onSeekSegment={
                    audioReady
                      ? (segmentId) => {
                          const start = segments?.[segmentId]?.start;
                          if (start != null) seekTo(start);
                        }
                      : undefined
                  }
                />
                <RefineActions
                  draft={draft}
                  sessionId={id}
                  onApproved={() => {
                    refine.getDraft(id).then(setDraft).catch(() => {});
                    setRegenerating(true); // show "Updating insights" until the re-derive lands
                  }}
                />
                {/* Task #20 — host-only contribution, enabled only post-v2-approval. */}
                <ContributeShapeOS sessionId={id} approved={draft.status === "approved"} />
              </>
            ) : (
              <TranscriptPanel
                sessionId={meeting.session_id}
                canView={meeting.can_view_transcript}
                workspaceId={meeting.workspace_id ?? null}
                canTag={Boolean(meeting.is_owner)}
                reloadKey={reloadKey}
                // Task #41 — click a segment to seek+play, only when audio is available.
                onSeek={audioReady ? seekTo : undefined}
              />
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No transcript available for this meeting.
          </p>
        )}

      </main>
    </AppShell>
  );
}

/** A header icon-button that toggles a bordered popover panel (no shadow). */
function IconPopover({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  label: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={label}
        title={label}
        aria-expanded={open}
        className={cn(
          "inline-flex size-9 items-center justify-center rounded-lg border border-border bg-card transition-colors",
          open
            ? "bg-secondary text-foreground"
            : "text-muted-foreground hover:bg-secondary hover:text-foreground",
        )}
      >
        <Icon className="size-4" aria-hidden />
      </button>
      {open ? (
        <div className="absolute right-0 z-50 mt-2 max-h-[70vh] w-[24rem] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-lg border border-border bg-card p-4 animate-in fade-in-0 zoom-in-95 slide-in-from-top-1 duration-150">
          {children}
        </div>
      ) : null}
    </div>
  );
}

function fmtDuration(sec: number): string {
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  return `${m}:${String(ss).padStart(2, "0")}`;
}

/**
 * Per-signal-kind accent: a colored left bar keeps the readout scannable via
 * signal-token colors (action=attested green, open_question=warn amber,
 * insight=entity blue).
 */
const SIGNAL_ACCENT: Record<string, { bar: string; dot: string }> = {
  action: { bar: "border-l-attested", dot: "bg-attested" },
  open_question: {
    bar: "border-l-signal-warn",
    dot: "bg-signal-warn",
  },
  insight: { bar: "border-l-signal-entity", dot: "bg-signal-entity" },
};

function SignalGroup({
  title,
  signals,
  accent,
}: {
  title: string;
  signals: Signal[];
  accent: keyof typeof SIGNAL_ACCENT;
}) {
  if (signals.length === 0) return null;
  const { bar, dot } = SIGNAL_ACCENT[accent];
  return (
    <section className="mb-8">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
        <span className={`size-2 rounded-sm ${dot}`} aria-hidden />
        {title}
      </h2>
      <ul className="flex flex-col gap-3">
        {signals.map((s, idx) => (
          <li
            key={`${s.kind}-${idx}`}
            className={`rounded-lg border border-border border-l-4 bg-card p-4 ${bar}`}
          >
            <p className="text-sm leading-relaxed text-foreground">{s.text}</p>
            {s.source_quote ? (
              <p className="mt-2 text-xs italic leading-relaxed text-muted-foreground">
                &ldquo;{s.source_quote}&rdquo;
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
