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

import { Bot, FileText, ShieldCheck } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { RecordMeetingButton } from "@/components/record-meeting";
import { UploadTranscriptButton } from "@/components/upload-transcript";
import { useWorkspace } from "@/components/workspace-provider";
import {
  ApiError,
  auth,
  bots,
  kb,
  workspaces,
  type ActiveInvitation,
  type KBObligation,
  type Meeting,
  type MeResponse,
} from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const { workspace, workspaces: wsList } = useWorkspace();
  const workspaceId = workspace?.id ?? null;
  const [me, setMe] = useState<MeResponse | null>(null);
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [active, setActive] = useState<ActiveInvitation[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Widget data — best-effort, non-blocking (null = still loading).
  const [obligations, setObligations] = useState<KBObligation[] | null>(null);

  // Initial load + active-list polling so "Live now" reflects state changes
  // (status transitions, completions) without needing the user to refresh.
  // Keyed on workspaceId: switching workspaces re-runs the whole load.
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
        if (workspaceId) {
          // Widget data rides along but never blocks the meetings list.
          kb.obligations(workspaceId)
            .then((r) => !cancelled && setObligations(r.obligations))
            .catch(() => !cancelled && setObligations([]));
          const m = await workspaces.meetings(workspaceId);
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
          if ((becameTerminal || hasProcessing) && workspaceId) {
            workspaces
              .meetings(workspaceId)
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
  }, [router, workspaceId]);

  async function handleStop(sessionId: string) {
    if (!confirm("Stop the bot for this meeting?")) return;
    try {
      await bots.stop(sessionId);
      setActive((prev) => prev.filter((a) => a.session_id !== sessionId));
      if (workspaceId) {
        const m = await workspaces.meetings(workspaceId);
        setMeetings(m.meetings);
      }
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to stop bot");
    }
  }

  if (error) return <PageError message={error} />;
  if (!me || wsList === null) return <PageLoading />;

  return (
    <AppShell user={me.user}>
      {/* Brutalist clean background canvas */}
      <main className="flex-1 bg-background">
        <div className="mx-auto w-full max-w-5xl px-6 py-8 md:py-10">
          
          {/* Brutalist Greeting Header */}
          <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between border-b border-border pb-6">
            <div>
              <h1 className="font-heading text-3xl font-black uppercase tracking-tight md:text-4xl text-foreground">
                {greeting()}, {me.user.email.split("@")[0]}
              </h1>
              <p className="mt-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Overview for {todayLabel()} · Confidential Enclave active
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {workspaceId ? (
                <>
                  <RecordMeetingButton workspaceId={workspaceId} />
                  <UploadTranscriptButton workspaceId={workspaceId} />
                </>
              ) : null}
              <Link
                href="/invite"
                aria-label="Invite bot"
                title="Invite bot"
                className="inline-flex size-10 items-center justify-center rounded-none border border-foreground bg-primary text-primary-foreground shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] dark:shadow-[2px_2px_0px_0px_rgba(255,255,255,1)] transition-all hover:bg-muted-foreground active:scale-95"
              >
                <Bot className="size-5" aria-hidden />
              </Link>
            </div>
          </div>

          {active.length > 0 ? (
            <section className="mb-6">
              <ul className="flex flex-col gap-2">
                {active.map((a) => (
                  <li
                    key={a.invitation_id}
                    className="flex items-center justify-between rounded-none border border-foreground bg-card px-5 py-3 shadow-[2px_2px_0px_0px_rgba(0,0,0,1)] dark:shadow-[2px_2px_0px_0px_rgba(255,255,255,1)]"
                  >
                    <div className="flex items-center gap-3">
                      <span className="relative flex h-2 w-2" aria-hidden>
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-attested opacity-60" />
                        <span className="relative inline-flex h-2 w-2 rounded-full bg-attested" />
                      </span>
                      <div>
                        <p className="font-mono text-xs font-bold">{a.session_id}</p>
                        <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          {humanStatus(a.status)} · started{" "}
                          {a.created_at.split("T")[1]?.slice(0, 5) ??
                            a.created_at}
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={() => handleStop(a.session_id)}
                      className="inline-flex h-7 items-center rounded-none border border-destructive bg-destructive/10 px-3 text-[10px] font-bold uppercase tracking-wider text-destructive hover:bg-destructive/20"
                    >
                      Stop
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {meetings !== null && meetings.length === 0 ? (
            <EmptyState />
          ) : (
            /* Widget grid: meetings list (2 cols) + right rail. */
            <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
              <div className="flex flex-col gap-8 md:col-span-2">
                {meetings
                  ?.filter((m) => m.is_processing)
                  .map((m) => (
                    <ProcessingCard key={m.session_id} meeting={m} />
                  ))}
                <RecentMeetings meetings={meetings} />
              </div>
              <div className="flex flex-col gap-8">
                <EnclaveCard />
                <UpNext obligations={obligations} />
              </div>
            </div>
          )}
        </div>
      </main>
    </AppShell>
  );
}

/** Motto Brutalist "Recently Viewed" widget */
function RecentMeetings({ meetings }: { meetings: Meeting[] | null }) {
  const done = meetings?.filter((m) => !m.is_processing);
  return (
    <div className="rounded-none border border-border bg-card p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,0.15)] dark:shadow-[4px_4px_0px_0px_rgba(255,255,255,0.15)]">
      <div className="mb-6 flex items-center justify-between border-b border-border pb-4">
        <h4 className="flex items-center gap-2 font-heading text-lg font-black uppercase tracking-tight">
          <FileText className="size-4 text-foreground" aria-hidden />
          Recent meetings
        </h4>
        <span className="text-[10px] font-bold tracking-widest text-muted-foreground uppercase">
          {done ? `${done.length} TOTAL` : ""}
        </span>
      </div>
      {done === null || done === undefined ? (
        <p className="p-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Loading meetings…</p>
      ) : (
        <div className="space-y-3">
          {done.map((m) => (
            <Link
              key={m.session_id}
              href={`/meeting/${m.session_id}`}
              className="group flex items-center justify-between rounded-none border border-border bg-secondary/55 p-3.5 transition hover:border-foreground hover:bg-card"
            >
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-none border border-border bg-card text-foreground shadow-sm">
                  <FileText className="size-4" aria-hidden />
                </div>
                <div className="min-w-0">
                  <div className="truncate text-xs font-bold uppercase tracking-wide">
                    {m.summary
                      ? truncate(m.summary, 90)
                      : `${m.source} — ${m.date}`}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5 text-[10px] font-mono text-muted-foreground">
                    {m.date} &bull; {m.source}
                    {isDemoSession(m.session_id) ? <DemoTag /> : null}
                  </div>
                </div>
              </div>
              <span className="text-muted-foreground/60 transition-transform group-hover:translate-x-1">
                &rarr;
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

/** Enclave Status Card with a bold brutalist frame */
function EnclaveCard() {
  return (
    <div className="group relative flex h-48 flex-col justify-between rounded-none border-2 border-foreground bg-foreground p-6 text-background shadow-[4px_4px_0px_0px_rgba(0,0,0,0.15)] dark:shadow-[4px_4px_0px_0px_rgba(255,255,255,0.15)] transition hover:translate-y-px">
      <div>
        <div className="mb-3 flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest text-background/50">
          <ShieldCheck className="size-3.5 text-attested" aria-hidden />
          Enclave Verified
        </div>
        <div className="font-heading text-2xl font-black uppercase tracking-tight">
          Operator-Blind
        </div>
      </div>
      <div>
        <div className="mb-2 flex items-center justify-between text-[10px] font-mono text-background/70">
          <span>Intel TDX · Hardware Seal</span>
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          <span className="relative flex h-2 w-2" aria-hidden>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-attested opacity-60" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-attested" />
          </span>
          <span className="font-bold uppercase tracking-wider text-background/95">
            Attested Environment
          </span>
        </div>
      </div>
    </div>
  );
}

/** Motto Brutalist "Up Next" widget */
function UpNext({ obligations }: { obligations: KBObligation[] | null }) {
  const open =
    obligations?.filter((o) => o.status_inferred === "open").slice(0, 4) ?? [];
  return (
    <div className="flex flex-1 flex-col rounded-none border border-border bg-card p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,0.15)] dark:shadow-[4px_4px_0px_0px_rgba(255,255,255,0.15)]">
      <div className="mb-6 flex items-center justify-between border-b border-border pb-4">
        <h4 className="font-heading text-lg font-black uppercase tracking-tight">
          Up next
        </h4>
        <span className="flex size-5 items-center justify-center border border-foreground bg-secondary text-[10px] font-bold">
          {obligations === null ? "…" : open.length}
        </span>
      </div>
      {obligations === null ? (
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Loading…</p>
      ) : open.length === 0 ? (
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Nothing open — caught up.
        </p>
      ) : (
        <div className="flex-1 space-y-4">
          {open.map((o) => (
            <Link
              key={o.id}
              href={`/meeting/${o.session_id}`}
              className="group flex items-start gap-3"
            >
              <div
                className="mt-0.5 size-4 shrink-0 rounded-none border-2 border-foreground bg-card transition-colors group-hover:bg-secondary"
                aria-hidden
              />
              <div className="min-w-0">
                <span className="line-clamp-2 text-xs font-bold uppercase tracking-wide text-foreground/80 transition group-hover:text-foreground">
                  {o.description}
                </span>
                {o.importance != null && o.importance >= 7 ? (
                  <span className="mt-1.5 inline-block rounded-full bg-red-100 dark:bg-red-900/30 px-2 py-0.5 text-[9px] font-bold text-destructive uppercase tracking-wider">
                    High priority
                  </span>
                ) : null}
              </div>
            </Link>
          ))}
        </div>
      )}
      <Link
        href="/obligations"
        className="mt-6 border-t border-border pt-4 text-[10px] font-bold tracking-widest text-muted-foreground transition hover:text-foreground uppercase"
      >
        VIEW ALL &rarr;
      </Link>
    </div>
  );
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Up late";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

/** "Monday, Oct 24"-style label (Vantage greeting subtext). */
function todayLabel(): string {
  return new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

const EXAMPLE_SESSION_ID = "example-conclave-demo";

/** Sessions seeded for demo purposes (Alembic 0009 + the example card). */
function isDemoSession(sessionId: string): boolean {
  return sessionId.startsWith("demo-") || sessionId === EXAMPLE_SESSION_ID;
}

/** Subtle mono tag so a prospect knows a card is sample data, not theirs. */
function DemoTag() {
  return (
    <span className="rounded-none border border-border bg-muted px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-wider text-muted-foreground">
      demo
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-none border border-border bg-card p-8 shadow-[4px_4px_0px_0px_rgba(0,0,0,0.15)] dark:shadow-[4px_4px_0px_0px_rgba(255,255,255,0.15)]">
        <p className="font-heading text-2xl font-black uppercase tracking-tight">
          Welcome to Conclave
        </p>
        <p className="mt-4 max-w-prose text-xs font-semibold leading-relaxed text-muted-foreground uppercase tracking-wide">
          Conclave gives you a confidential transcript and signal extraction
          for every meeting you invite our bot to. Transcription happens
          inside a TEE — operator-blind from end to end.
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <Link
            href={`/meeting/${EXAMPLE_SESSION_ID}`}
            className="text-xs font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground border-b border-transparent hover:border-foreground pb-0.5"
          >
            browse example meeting &rarr;
          </Link>
        </div>
      </div>
      <ul className="grid gap-6 sm:grid-cols-2">
        <li>
          <Link
            href={`/meeting/${EXAMPLE_SESSION_ID}`}
            className="group flex h-full flex-col justify-between rounded-none border border-border bg-card p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,0.15)] dark:shadow-[4px_4px_0px_0px_rgba(255,255,255,0.15)] transition hover:border-foreground"
          >
            <p className="text-sm font-bold uppercase tracking-wide leading-snug transition-colors group-hover:text-primary">
              Walkthrough of how a Conclave meeting card looks once your bot
              has joined a Meet.
            </p>
            <p className="mt-4 flex items-center gap-2 font-mono text-[10px] font-bold text-muted-foreground uppercase">
              2026-05-15 &bull; example
              <DemoTag />
            </p>
          </Link>
        </li>
      </ul>
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
    <div className="rounded-none border border-primary bg-card p-6 shadow-sm">
      <div className="flex items-center gap-3">
        <span
          className="inline-block h-2.5 w-2.5 animate-pulse rounded-none bg-primary"
          aria-hidden
        />
        <p className="animate-shimmer-text text-sm font-bold uppercase tracking-wider">
          {PROCESSING_MESSAGES[phraseIdx]}
        </p>
      </div>
      <p className="mt-3 font-mono text-[10px] font-bold text-muted-foreground uppercase">
        {meeting.date} &bull; {meeting.source} &bull; {meeting.session_id}
      </p>
      <p className="mt-2 text-xs text-muted-foreground">
        This card refreshes itself when the LLM finishes — usually under two
        minutes. You can close this tab; the meeting will be ready when you
        come back.
      </p>
    </div>
  );
}
