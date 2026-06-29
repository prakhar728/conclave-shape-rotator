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

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { OwnerControls } from "@/components/owner-controls";
import { PageError, PageLoading } from "@/components/page-state";
import { ContributeShapeOS } from "@/components/refine/contribute-shapeos";
import { InsightsPlaceholder } from "@/components/refine/insights-placeholder";
import { RefineActions } from "@/components/refine/refine-actions";
import { RefineEditor } from "@/components/refine/refine-editor";
import { useRefineDraft } from "@/components/refine/use-refine-draft";
import { RetentionControl } from "@/components/retention-control";
import { TranscriptPanel } from "@/components/transcript-panel";
import {
  ApiError,
  auth,
  meetings as meetingsApi,
  refine,
  type MeResponse,
  type MeetingView,
  type Signal,
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

  // After approve, the summary + signals re-derive from the corrected v2 in the
  // background. Poll the draft until its `insights_stale` clears (the re-derive's
  // done-signal), then pull the fresh meeting signals — surfacing an "Updating
  // insights" sign throughout.
  useEffect(() => {
    if (!regenerating) return;
    let n = 0;
    const iv = setInterval(async () => {
      n += 1;
      try {
        const d = await refine.getDraft(id);
        setDraft(d);
        if (!d.insights_stale || n >= 45) {
          clearInterval(iv);
          setMeeting(await meetingsApi.get(id));
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

  return (
    <AppShell user={me.user}>
      <main className="mx-auto max-w-3xl px-6 py-10">
        <Link
          href="/dashboard"
          className="text-xs font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground border-b border-transparent hover:border-foreground pb-0.5"
        >
          &larr; Back to Dashboard
        </Link>
        
        <div className="mt-8 mb-10 border-b border-border pb-6">
          <h1 className="font-heading text-3xl font-black uppercase tracking-tight leading-none text-foreground sm:text-4xl">
            {meeting.summary || `${meeting.source} — ${meeting.date}`}
          </h1>
          <p className="mt-3 font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            {meeting.date} &bull; {meeting.source} &bull; {meeting.session_id}
          </p>

          {meeting.meeting_intent_version ? (
            <p
              data-testid="agenda-grounded"
              title={`meeting_intent_version: ${meeting.meeting_intent_version}`}
              className="mt-2 inline-flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-wider text-primary"
            >
              <span className="size-1.5 rounded-full bg-primary" />
              Agenda-grounded insights
            </p>
          ) : null}

        </div>

        {processing ? (
          <div className="mb-8 flex items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 px-4 py-3">
            <span className="size-2 animate-pulse rounded-full bg-primary" />
            <p className="text-xs text-muted-foreground">
              Post-processing — showing the live diart transcript. The final re-diarized transcript,
              speaker names, and summary will appear here automatically when ready.
            </p>
          </div>
        ) : null}

        {regenerating ? (
          <div
            data-testid="insights-updating"
            className="mb-8 flex items-center gap-3 rounded-xl border border-blue-500/30 bg-blue-500/5 px-4 py-3"
          >
            <span className="size-2 animate-pulse rounded-full bg-blue-500" />
            <p className="text-xs text-muted-foreground">
              Updating insights — re-deriving the summary &amp; signals from your approved corrections…
            </p>
          </div>
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

        {meeting.is_owner ? (
          <div className="space-y-6 mt-12 border-t border-border pt-8">
            <OwnerControls
              sessionId={meeting.session_id}
              initialVisibility={
                (meeting.effective_visibility as "owner-only" | "shared") ??
                "owner-only"
              }
            />
            <RetentionControl
              sessionId={meeting.session_id}
              initialOverride={meeting.retention_override}
              rawDeleted={meeting.raw_transcript_deleted}
            />
          </div>
        ) : null}

        {meeting.entities.length > 0 ? (
          <section className="mt-10 border-t border-border pt-8">
            <h2 className="mb-4 font-heading text-xs font-bold uppercase tracking-widest text-muted-foreground">
              Entities Mentioned
            </h2>
            <ul className="flex flex-wrap gap-2.5">
              {meeting.entities.map((e, idx) => (
                <li key={`${e.name}-${idx}`}>
                  <Link
                    href={`/entity/${encodeURIComponent(e.name)}`}
                    className="inline-block rounded-none border border-border bg-card px-3.5 py-1.5 text-xs font-semibold tracking-wide transition-colors hover:border-foreground hover:bg-secondary"
                  >
                    <span className="text-foreground uppercase">{e.name}</span>
                    <span className="ml-2.5 text-[10px] font-mono text-muted-foreground uppercase">{e.type}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {meeting.can_view_transcript !== undefined ? (
          <div className="mt-10 border-t border-border pt-8">
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
              />
            )}
          </div>
        ) : null}
      </main>
    </AppShell>
  );
}

/**
 * Per-signal-kind accent (UI-NOW.md §3): colored left bar on each card
 * makes the readout scannable in 2 seconds — same color language as the
 * obligations board (action=cyber-green, open_question=amber, insight=sky).
 */
const SIGNAL_ACCENT: Record<string, { bar: string; dot: string }> = {
  action: { bar: "border-l-attested", dot: "bg-attested" },
  open_question: {
    bar: "border-l-yellow-500",
    dot: "bg-yellow-500",
  },
  insight: { bar: "border-l-blue-500", dot: "bg-blue-500" },
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
      <h2 className="mb-4 flex items-center gap-2 font-heading text-xs font-bold uppercase tracking-widest text-foreground">
        <span className={`size-2 rounded-none ${dot}`} aria-hiddenBytes />
        {title}
      </h2>
      <ul className="flex flex-col gap-3">
        {signals.map((s, idx) => (
          <li
            key={`${s.kind}-${idx}`}
            className={`rounded-none border border-border border-l-4 bg-card p-4 shadow-sm ${bar}`}
          >
            <p className="text-xs font-bold uppercase tracking-wide leading-relaxed">{s.text}</p>
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
