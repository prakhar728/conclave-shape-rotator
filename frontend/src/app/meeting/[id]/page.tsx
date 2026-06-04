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

import { AppHeader } from "@/components/app-header";
import { OwnerControls } from "@/components/owner-controls";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="text-center">
          <p className="text-sm text-destructive">{error}</p>
          <Link
            href="/dashboard"
            className="mt-3 inline-block text-xs text-muted-foreground hover:text-foreground"
          >
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }
  if (!me || !meeting) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <AppHeader user={me.user} workspace={me.workspace} />
      <main className="mx-auto max-w-3xl px-6 py-10">
        <Link
          href="/dashboard"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          ← Back
        </Link>
        <div className="mt-3 mb-8">
          <h1 className="text-2xl font-semibold tracking-tight">
            {meeting.summary || `${meeting.source} — ${meeting.date}`}
          </h1>
          <p className="mt-2 text-xs text-muted-foreground">
            {meeting.date} · {meeting.source} · {meeting.session_id}
          </p>
        </div>

        <SignalGroup
          title="Action items"
          signals={meeting.signals_by_kind.action_items}
        />
        <SignalGroup
          title="Open questions"
          signals={meeting.signals_by_kind.open_questions}
        />
        <SignalGroup
          title="Insights"
          signals={meeting.signals_by_kind.insights}
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
                    className="inline-block rounded-full border border-border px-3 py-1 text-xs transition-colors hover:border-foreground/40"
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
    </div>
  );
}

function SignalGroup({
  title,
  signals,
}: {
  title: string;
  signals: Signal[];
}) {
  if (signals.length === 0) return null;
  return (
    <section className="mb-6">
      <h2 className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
        {title}
      </h2>
      <ul className="flex flex-col gap-2">
        {signals.map((s, idx) => (
          <li key={`${s.kind}-${idx}`}>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">{s.text}</CardTitle>
              </CardHeader>
              {s.source_quote ? (
                <CardContent>
                  <p className="text-xs italic text-muted-foreground">
                    &ldquo;{s.source_quote}&rdquo;
                  </p>
                </CardContent>
              ) : null}
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}
