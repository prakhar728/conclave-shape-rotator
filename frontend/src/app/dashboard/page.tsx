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

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import {
  ApiError,
  auth,
  bots,
  kb,
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
  // Stat-card counts — best-effort, non-blocking (null = still loading).
  const [entityCount, setEntityCount] = useState<number | null>(null);
  const [obligationCount, setObligationCount] = useState<number | null>(null);

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
          // Stat counts ride along but never block the meetings list.
          kb.entities(meResp.workspace.id)
            .then((r) => !cancelled && setEntityCount(r.entities.length))
            .catch(() => !cancelled && setEntityCount(0));
          kb.obligations(meResp.workspace.id)
            .then((r) => !cancelled && setObligationCount(r.obligations.length))
            .catch(() => !cancelled && setObligationCount(0));
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

  if (error) return <PageError message={error} />;
  if (!me) return <PageLoading />;

  return (
    <AppShell user={me.user} workspace={me.workspace}>
      <main className="mx-auto w-full max-w-5xl px-6 py-8">
        <div className="mb-8 flex items-baseline justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {greeting()}, {me.user.email.split("@")[0]}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Here&apos;s what your meetings know.
            </p>
          </div>
          <Link
            href="/invite"
            className="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/85"
          >
            Invite bot
          </Link>
        </div>

        {/* Stat summary cards */}
        <div className="mb-8 grid gap-4 sm:grid-cols-3">
          <StatCard
            label="Meetings"
            value={meetings?.length ?? null}
            href="/dashboard"
            tint="bg-primary/10 text-primary"
          />
          <StatCard
            label="Open obligations"
            value={obligationCount}
            href="/obligations"
            tint="bg-signal-speaker/10 text-signal-speaker"
          />
          <StatCard
            label="Entities tracked"
            value={entityCount}
            href="/entities"
            tint="bg-signal-entity/10 text-signal-entity"
          />
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

        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Recent meetings
        </p>
        {meetings === null ? (
          <p className="text-sm text-muted-foreground">Loading meetings…</p>
        ) : meetings.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2">
            {meetings.map((m) =>
              m.is_processing ? (
                <li key={m.session_id} className="sm:col-span-2">
                  <ProcessingCard meeting={m} />
                </li>
              ) : (
                <li key={m.session_id}>
                  <Link
                    href={`/meeting/${m.session_id}`}
                    className="group flex h-full flex-col justify-between rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
                  >
                    <p className="text-sm font-semibold leading-snug transition-colors group-hover:text-primary">
                      {m.summary
                        ? truncate(m.summary, 120)
                        : `${m.source} — ${m.date}`}
                    </p>
                    <p className="mt-3 flex items-center gap-2 font-mono text-xs text-muted-foreground">
                      {m.date} · {m.source}
                      {isDemoSession(m.session_id) ? <DemoTag /> : null}
                    </p>
                  </Link>
                </li>
              ),
            )}
          </ul>
        )}
      </main>
    </AppShell>
  );
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Up late";
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

/** Dashboard stat summary card; value=null renders a quiet placeholder. */
function StatCard({
  label,
  value,
  href,
  tint,
}: {
  label: string;
  value: number | null;
  href: string;
  tint: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
    >
      <span
        className={`inline-flex rounded-lg px-2 py-1 text-xs font-semibold ${tint}`}
      >
        {label}
      </span>
      <p className="mt-3 text-3xl font-bold tracking-tight">
        {value ?? "–"}
      </p>
    </Link>
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
      <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
        <p className="text-xl font-bold tracking-tight">
          Welcome to Conclave<span className="text-primary">.</span>
        </p>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">
          Conclave gives you a confidential transcript and signal extraction
          for every meeting you invite our bot to. Transcription happens
          inside a TEE — operator-blind from end to end.
        </p>
        <div className="mt-5 flex flex-wrap items-center gap-4">
          <Link
            href="/invite"
            className="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/85"
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
      <ul className="grid gap-4 sm:grid-cols-2">
        <li>
          <Link
            href={`/meeting/${EXAMPLE_SESSION_ID}`}
            className="group flex h-full flex-col justify-between rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md"
          >
            <p className="text-sm font-semibold leading-snug transition-colors group-hover:text-primary">
              Walkthrough of how a Conclave meeting card looks once your bot
              has joined a Meet.
            </p>
            <p className="mt-3 flex items-center gap-2 font-mono text-xs text-muted-foreground">
              2026-05-15 · example
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
    <div className="rounded-xl border border-primary/30 bg-card p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <span
          className="inline-block h-2 w-2 animate-pulse rounded-full bg-primary"
          aria-hidden
        />
        <p className="animate-shimmer-text text-sm font-semibold">
          {PROCESSING_MESSAGES[phraseIdx]}
        </p>
      </div>
      <p className="mt-2 font-mono text-xs text-muted-foreground">
        {meeting.date} · {meeting.source} · {meeting.session_id}
      </p>
      <p className="mt-2 text-xs text-muted-foreground">
        This card refreshes itself when the LLM finishes — usually under two
        minutes. You can close this tab; the meeting will be ready when you
        come back.
      </p>
    </div>
  );
}
