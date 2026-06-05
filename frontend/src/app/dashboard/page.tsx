/**
 * /dashboard — primary signed-in view.
 *
 * Fetches the current user + default workspace via /api/auth/v1/me, then
 * the workspace's meetings list. Empty state lands proper in 1.16
 * (welcome CTA + example meeting); this version just renders the
 * cards-or-empty branch.
 *
 * If /me 401s (cookie missing / expired), redirect to /login. Middleware
 * catches the no-cookie case at the edge already; this guards the
 * cookie-present-but-invalid case too.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  auth,
  bots,
  workspaces,
  type ActiveInvitation,
  type Meeting,
  type MeResponse,
} from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [active, setActive] = useState<ActiveInvitation[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Initial load + active-list polling so "Live now" reflects state changes
  // (status transitions, completions) without needing the user to refresh.
  useEffect(() => {
    let cancelled = false;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    async function loadAll() {
      try {
        const [meResp, activeResp] = await Promise.all([
          auth.me(),
          bots.active().catch(() => ({ active: [] as ActiveInvitation[] })),
        ]);
        if (cancelled) return;
        setMe(meResp);
        setActive(activeResp.active);
        if (meResp.workspace) {
          const m = await workspaces.meetings(meResp.workspace.id);
          if (!cancelled) setMeetings(m.meetings);
        } else {
          setMeetings([]);
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load dashboard");
      }
    }
    loadAll();
    // Re-poll the cheap "active" list every 7s so the user sees live bots
    // come and go. Also re-pull the meetings list on every tick when there's
    // a processing card visible (or when something just fell off active) so
    // the in-progress card morphs into a real card as soon as enrichment
    // completes.
    intervalId = setInterval(async () => {
      try {
        const r = await bots.active();
        if (cancelled) return;
        setActive((prev) => {
          const becameTerminal = prev.length > r.active.length;
          const hasProcessing = (meetings ?? []).some((m) => m.is_processing);
          if ((becameTerminal || hasProcessing) && me?.workspace) {
            workspaces
              .meetings(me.workspace.id)
              .then((mr) => !cancelled && setMeetings(mr.meetings))
              .catch(() => {});
          }
          return r.active;
        });
      } catch {
        // Silent — next tick retries.
      }
    }, 7000);
    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function handleStop(sessionId: string) {
    if (!confirm("Stop the bot for this meeting?")) return;
    try {
      await bots.stop(sessionId);
      setActive((prev) => prev.filter((a) => a.session_id !== sessionId));
      if (me?.workspace) {
        const m = await workspaces.meetings(me.workspace.id);
        setMeetings(m.meetings);
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to stop bot");
    }
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    );
  }
  if (!me) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <AppHeader user={me.user} workspace={me.workspace} />
      <main className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-8 flex items-baseline justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Meetings</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {me.workspace?.name ?? "No workspace"}
            </p>
          </div>
          <Link
            href="/invite"
            className="inline-flex h-8 items-center rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/80"
          >
            Invite bot
          </Link>
        </div>

        {active.length > 0 ? (
          <section className="mb-8">
            <p className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Live now
            </p>
            <ul className="flex flex-col gap-2">
              {active.map((a) => (
                <li
                  key={a.invitation_id}
                  className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3"
                >
                  <div className="flex items-center gap-3">
                    <span
                      className="h-2 w-2 rounded-full bg-attested"
                      aria-hidden
                    />
                    <div>
                      <p className="font-mono text-sm">{a.session_id}</p>
                      <p className="text-xs text-muted-foreground">
                        {humanStatus(a.status)} · started{" "}
                        {a.created_at.split("T")[1]?.slice(0, 5) ?? a.created_at}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => handleStop(a.session_id)}
                    className="inline-flex h-7 items-center rounded-lg border border-destructive/40 bg-destructive/10 px-3 text-xs font-medium text-destructive hover:bg-destructive/20"
                  >
                    Stop
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {meetings === null ? (
          <p className="text-sm text-muted-foreground">Loading meetings…</p>
        ) : meetings.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex flex-col gap-3">
            {meetings.map((m) =>
              m.is_processing ? (
                <li key={m.session_id}>
                  <ProcessingCard meeting={m} />
                </li>
              ) : (
                <li key={m.session_id}>
                  <Link href={`/meeting/${m.session_id}`}>
                    <Card className="transition-colors hover:border-primary/30">
                      <CardHeader>
                        <CardTitle className="text-base">
                          {m.summary
                            ? truncate(m.summary, 120)
                            : `${m.source} — ${m.date}`}
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <p className="flex items-center gap-2 text-xs text-muted-foreground">
                          {m.date} · {m.source}
                          {isDemoSession(m.session_id) ? <DemoTag /> : null}
                        </p>
                      </CardContent>
                    </Card>
                  </Link>
                </li>
              ),
            )}
          </ul>
        )}
      </main>
    </div>
  );
}

const EXAMPLE_SESSION_ID = "example-conclave-demo";

/** Sessions seeded for demo purposes (Alembic 0009 + the example card). */
function isDemoSession(sessionId: string): boolean {
  return sessionId.startsWith("demo-") || sessionId === EXAMPLE_SESSION_ID;
}

/** Subtle mono tag so a prospect knows a card is sample data, not theirs. */
function DemoTag() {
  return (
    <span className="rounded-full border border-border bg-muted px-1.5 py-px font-mono text-[10px] leading-4 text-muted-foreground">
      demo
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border border-border bg-card p-6">
        <p className="text-sm font-medium">Welcome to Conclave</p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Conclave gives you a confidential transcript and signal extraction
          for every meeting you invite our bot to. Transcription happens
          inside a TEE — operator-blind from end to end.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Link
            href="/invite"
            className="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80"
          >
            Invite the bot to a meeting
          </Link>
          <Link
            href={`/meeting/${EXAMPLE_SESSION_ID}`}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            or browse the example meeting →
          </Link>
        </div>
      </div>
      <div>
        <p className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Example meeting
        </p>
        <Link href={`/meeting/${EXAMPLE_SESSION_ID}`}>
          <Card className="transition-colors hover:border-primary/30">
            <CardHeader>
              <CardTitle className="text-base">
                Walkthrough of how a Conclave meeting card looks once your
                bot has joined a Meet.
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                2026-05-15 · example
                <DemoTag />
              </p>
            </CardContent>
          </Card>
        </Link>
      </div>
    </div>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function humanStatus(s: ActiveInvitation["status"]): string {
  switch (s) {
    case "requested":
      return "Queueing bot";
    case "joining":
      return "Joining meeting";
    case "active":
      return "Transcribing";
    case "completed":
      return "Wrapped";
    case "failed":
      return "Failed";
  }
}

// Quirky messages cycled while a meeting is between webhook arrival and
// LLM enrichment completion. Window is typically 30s-2min. Picked to read
// like the system is doing real work, not stuck.
const PROCESSING_MESSAGES = [
  "Transcribing the audio…",
  "Sharpening insights…",
  "Reading between the lines…",
  "Distilling action items…",
  "Finding open questions…",
  "Surfacing what was decided…",
  "Threading the conversation together…",
  "Almost there…",
];

function ProcessingCard({ meeting }: { meeting: Meeting }) {
  const [phraseIdx, setPhraseIdx] = useState(0);
  useEffect(() => {
    const id = setInterval(
      () => setPhraseIdx((i) => (i + 1) % PROCESSING_MESSAGES.length),
      2200,
    );
    return () => clearInterval(id);
  }, []);
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="flex items-center gap-3">
        <span
          className="inline-block h-2 w-2 animate-pulse rounded-full bg-primary"
          aria-hidden
        />
        <p className="animate-shimmer-text text-sm font-medium">
          {PROCESSING_MESSAGES[phraseIdx]}
        </p>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {meeting.date} · {meeting.source} ·{" "}
        <span className="font-mono">{meeting.session_id}</span>
      </p>
      <p className="mt-3 text-xs text-muted-foreground">
        The card refreshes itself when the LLM finishes — usually under two
        minutes. You can close this tab; the meeting will be ready when you
        come back.
      </p>
    </div>
  );
}
