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

import { ArrowRight, Bot, FileText, ShieldAlert, ShieldCheck } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { RecordMeetingButton } from "@/components/record-meeting";
import { UploadTranscriptButton } from "@/components/upload-transcript";
import { useWorkspace } from "@/components/workspace-provider";
import {
  ApiError,
  attestation,
  auth,
  bots,
  isAttested,
  kb,
  workspaces,
  type ActiveInvitation,
  type Attestation,
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
              <h1 className="font-heading text-2xl font-bold tracking-tight md:text-3xl text-foreground">
                {greeting()}, {me.user.email.split("@")[0]}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
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
                className="inline-flex size-10 items-center justify-center rounded-lg border border-border bg-card text-foreground transition-colors hover:bg-secondary"
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
                    className="flex items-center justify-between rounded-none border border-foreground bg-card px-5 py-3"
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

/** Recent meetings list. */
function RecentMeetings({ meetings }: { meetings: Meeting[] | null }) {
  const done = meetings?.filter((m) => !m.is_processing);
  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-base font-bold tracking-tight">Recent meetings</h4>
        {done ? (
          <span className="rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground">
            {done.length} total
          </span>
        ) : null}
      </div>
      {done === null || done === undefined ? (
        <p className="py-3 text-sm text-muted-foreground">Loading meetings…</p>
      ) : (
        <div className="-mx-2 divide-y divide-border">
          {done.map((m) => (
            <Link
              key={m.session_id}
              href={`/meeting/${m.session_id}`}
              className="group flex items-center gap-3 rounded-lg px-2 py-3 transition-colors hover:bg-secondary/50"
            >
              <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-foreground">
                  {m.summary ? truncate(m.summary, 90) : `${m.source} · ${m.date}`}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                  {m.date} · {m.source}
                  {isDemoSession(m.session_id) ? <DemoTag /> : null}
                </div>
              </div>
              <ArrowRight
                className="size-4 shrink-0 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground"
                aria-hidden
              />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Enclave status card — reflects the REAL attestation state. Green
 * "Operator-Blind / Attested Environment" only when the backend returns a real
 * TDX quote; otherwise an honest amber "Local Mode / Not Attested" (running
 * outside a TEE, e.g. local dev, or the dstack agent is unreachable).
 */
function EnclaveCard() {
  const [att, setAtt] = useState<Attestation | null>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    attestation
      .get()
      .then((a) => !cancelled && setAtt(a))
      .catch(() => {})
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, []);
  const attested = isAttested(att);

  return (
    <div className="flex h-48 flex-col justify-between rounded-xl bg-foreground p-6 text-background">
      <div>
        <div className="mb-3 flex items-center gap-1.5 text-xs font-medium text-background/60">
          {attested ? (
            <ShieldCheck className="size-4 text-attested" aria-hidden />
          ) : (
            <ShieldAlert className="size-4 text-signal-warn" aria-hidden />
          )}
          {!loaded ? "Checking…" : attested ? "Enclave verified" : "Not attested"}
        </div>
        <div className="font-heading text-2xl font-bold tracking-tight">
          {attested ? "Operator-blind" : "Local mode"}
        </div>
      </div>
      <div>
        <div className="mb-2 text-xs text-background/60">
          {attested ? "Intel TDX · hardware seal" : "No hardware seal · local dev"}
        </div>
        <div className="flex items-center gap-2 text-sm">
          {attested ? (
            <span className="relative flex size-2" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-attested opacity-60" />
              <span className="relative inline-flex size-2 rounded-full bg-attested" />
            </span>
          ) : (
            <span
              className={`size-2 rounded-full ${loaded ? "bg-signal-warn" : "bg-background/40"}`}
              aria-hidden
            />
          )}
          <span className="font-medium text-background/90">
            {!loaded
              ? "Checking attestation"
              : attested
                ? "Attested environment"
                : "Development, not attested"}
          </span>
        </div>
      </div>
    </div>
  );
}

/** "Up next" — open obligations. */
function UpNext({ obligations }: { obligations: KBObligation[] | null }) {
  const open =
    obligations?.filter((o) => o.status_inferred === "open").slice(0, 4) ?? [];
  return (
    <div className="flex flex-1 flex-col rounded-xl border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <h4 className="text-base font-bold tracking-tight">Up next</h4>
        <span className="rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground">
          {obligations === null ? "…" : open.length}
        </span>
      </div>
      {obligations === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : open.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing open, all caught up.</p>
      ) : (
        <div className="flex-1 space-y-3">
          {open.map((o) => (
            <Link
              key={o.id}
              href={`/meeting/${o.session_id}`}
              className="group flex items-start gap-3"
            >
              <span
                className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/40"
                aria-hidden
              />
              <div className="min-w-0">
                <span className="line-clamp-2 text-sm text-foreground/80 transition group-hover:text-foreground">
                  {o.description}
                </span>
                {o.importance != null && o.importance >= 7 ? (
                  <span className="mt-1 inline-block rounded-md bg-destructive/10 px-2 py-0.5 text-[10px] font-medium text-destructive">
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
        className="mt-6 flex items-center gap-1 border-t border-border pt-4 text-sm font-medium text-muted-foreground transition hover:text-foreground"
      >
        View all <ArrowRight className="size-4" aria-hidden />
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

/** "Monday, Oct 24"-style label for the greeting subtext. */
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
      <div className="rounded-none border border-border bg-card p-8">
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
            className="group flex h-full flex-col justify-between rounded-none border border-border bg-card p-6 transition hover:border-foreground"
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
    <Link
      href={`/meeting/${meeting.session_id}`}
      className="group block rounded-xl border border-border bg-card p-6 transition-colors hover:border-foreground/30 hover:bg-secondary/30"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="inline-block size-2 shrink-0 animate-pulse rounded-full bg-primary"
            aria-hidden
          />
          <p className="animate-shimmer-text truncate text-sm font-medium">
            {PROCESSING_MESSAGES[phraseIdx]}
          </p>
        </div>
        <ArrowRight
          className="size-4 shrink-0 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground"
          aria-hidden
        />
      </div>
      <p className="mt-2 font-mono text-[10px] text-muted-foreground">
        {meeting.date} · {meeting.source} · {meeting.session_id}
      </p>
      <p className="mt-2 text-xs text-muted-foreground">
        Insights are still generating. The transcript is ready now, open it and the
        summary fills in automatically (usually under two minutes).
      </p>
    </Link>
  );
}
