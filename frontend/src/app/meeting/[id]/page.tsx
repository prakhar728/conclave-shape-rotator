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
 *
 * Raw transcript is deliberately not requested — the endpoint never
 * serves raw_diarization (see api/transcripts_routes.py docstring).
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { OwnerControls } from "@/components/owner-controls";
import { PageError, PageLoading } from "@/components/page-state";
import {
  ApiError,
  auth,
  meetings as meetingsApi,
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
    <AppShell user={me.user} workspace={me.workspace}>
      <main className="mx-auto max-w-3xl px-6 py-10">
        <Link
          href="/dashboard"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          ← Back
        </Link>
        <div className="mt-4 mb-10">
          <h1 className="text-2xl font-bold leading-snug tracking-tight">
            {meeting.summary || `${meeting.source} — ${meeting.date}`}
          </h1>
          <p className="mt-3 font-mono text-xs text-muted-foreground">
            {meeting.date} · {meeting.source} · {meeting.session_id}
          </p>
        </div>

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

        {meeting.is_owner ? (
          <OwnerControls
            sessionId={meeting.session_id}
            initialVisibility={
              (meeting.effective_visibility as "owner-only" | "shared") ??
              "owner-only"
            }
          />
        ) : null}

        {meeting.entities.length > 0 ? (
          <section className="mt-8">
            <h2 className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Entities
            </h2>
            <ul className="flex flex-wrap gap-2">
              {meeting.entities.map((e, idx) => (
                <li key={`${e.name}-${idx}`}>
                  {/* 3.5b C21 — chips link to the entity page. The KB
                      entity may not exist (pipeline flag off / older
                      sessions); the entity page 404-states gracefully. */}
                  <Link
                    href={`/entity/${encodeURIComponent(e.name)}`}
                    className="inline-block rounded-full border border-border px-3 py-1 text-xs transition-colors hover:border-primary/50"
                  >
                    <span className="text-foreground">{e.name}</span>
                    <span className="ml-2 text-muted-foreground">{e.type}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}

/**
 * Per-signal-kind accent (UI-NOW.md §3): colored left bar on each card
 * makes the readout scannable in 2 seconds — same color language as the
 * obligations board (action=emerald, open_question=amber, insight=sky).
 */
const SIGNAL_ACCENT: Record<string, { bar: string; dot: string }> = {
  action: { bar: "border-l-primary", dot: "bg-primary" },
  open_question: {
    bar: "border-l-signal-speaker",
    dot: "bg-signal-speaker",
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
      <h2 className="mb-4 flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-muted-foreground">
        <span className={`size-1.5 rounded-full ${dot}`} aria-hidden />
        {title}
      </h2>
      <ul className="flex flex-col gap-4">
        {signals.map((s, idx) => (
          <li key={`${s.kind}-${idx}`} className={`border-l-2 ${bar} pl-4`}>
            <p className="text-sm leading-relaxed">{s.text}</p>
            {s.source_quote ? (
              <p className="mt-1.5 text-sm italic leading-relaxed text-muted-foreground">
                &ldquo;{s.source_quote}&rdquo;
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
