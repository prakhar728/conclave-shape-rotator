/**
 * /invite — paste a Meet URL/code + optional attendee emails → launch bot.
 *
 * Three states:
 *   1. Form (email[]+meet URL) → POST /api/meetings/invite-bot
 *   2. Live status — polls /bot-status every 5s; renders the state badge
 *      (requested → joining → active → completed | failed)
 *   3. After completion: link to /meeting/{session_id}
 *
 * Polling stops on terminal states. WebSocket would be nicer but BUILD_DOC
 * §2.3 explicitly defers WS to v1.5.
 */
"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { PageLoading } from "@/components/page-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  auth,
  bots,
  type BotStatus,
  type MeResponse,
} from "@/lib/api";

const POLL_MS = 5000;
const TERMINAL: BotStatus[] = ["completed", "failed"];

type LiveState = {
  invitationId: string;
  sessionId: string;
  status: BotStatus;
};

export default function InvitePage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [meetInput, setMeetInput] = useState("");
  const [attendees, setAttendees] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<LiveState | null>(null);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    auth
      .me()
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  // Polling — restarted whenever we have a live invitation that's not terminal.
  useEffect(() => {
    if (!live || TERMINAL.includes(live.status)) {
      if (pollRef.current) clearTimeout(pollRef.current);
      return;
    }
    pollRef.current = setTimeout(async () => {
      try {
        const next = await bots.status(live.sessionId);
        setLive((cur) =>
          cur ? { ...cur, status: next.status } : cur,
        );
      } catch {
        // Transient failure — keep the previous status; next tick retries.
      }
    }, POLL_MS);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [live]);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!me?.workspace) {
      setError("No workspace — try refreshing the page.");
      return;
    }
    const emails = attendees
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter(Boolean);
    setBusy(true);
    setError(null);
    try {
      const resp = await bots.invite({
        meet_url_or_code: meetInput.trim(),
        workspace_id: me.workspace.id,
        attendee_emails: emails.length ? emails : undefined,
      });
      setLive({
        invitationId: resp.invitation_id,
        sessionId: resp.meeting_session_id,
        status: resp.status,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setError("That doesn't look like a Google Meet link or code.");
      } else if (err instanceof ApiError && err.status === 502) {
        setError(
          "The bot service didn't respond. Recato may be down; check the local stack and try again.",
        );
      } else {
        setError(err instanceof Error ? err.message : "Failed to invite bot");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!me) return <PageLoading />;

  return (
    <div className="min-h-screen bg-background">
      <AppHeader user={me.user} workspace={me.workspace} />
      <main className="mx-auto max-w-2xl px-6 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-bold tracking-tight">
            Invite the bot
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Paste a Google Meet URL or its <code className="font-mono">abc-defg-hij</code> code.
            We&apos;ll send the Conclave bot — admit it from inside the
            meeting, and the transcript lands here when you&apos;re done.
          </p>
        </div>

        {live ? (
          <LivePanel
            live={live}
            onStopped={() =>
              setLive((cur) =>
                cur ? { ...cur, status: "completed" } : cur,
              )
            }
          />
        ) : (
          <form onSubmit={handleInvite} className="flex flex-col gap-4">
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                Meet URL or code
              </label>
              <Input
                className="mt-2"
                autoFocus
                value={meetInput}
                onChange={(e) => setMeetInput(e.target.value)}
                placeholder="https://meet.google.com/abc-defg-hij"
                disabled={busy}
                required
              />
            </div>
            <div>
              <label className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                Attendees (optional)
              </label>
              <textarea
                className="mt-2 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                rows={3}
                value={attendees}
                onChange={(e) => setAttendees(e.target.value)}
                placeholder={"alice@example.com\nbob@example.com"}
                disabled={busy}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                One per line or comma-separated. They&apos;ll get a magic
                link to view the meeting once it&apos;s processed.
              </p>
            </div>
            <Button type="submit" disabled={busy || !meetInput.trim()}>
              {busy ? "Sending bot…" : "Send bot"}
            </Button>
            {error ? <p className="text-xs text-destructive">{error}</p> : null}
          </form>
        )}
      </main>
    </div>
  );
}

function LivePanel({
  live,
  onStopped,
}: {
  live: LiveState;
  onStopped: () => void;
}) {
  const isTerminal = TERMINAL.includes(live.status);
  const isFailure = live.status === "failed";
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);

  async function handleStop() {
    if (!confirm("Stop the bot and end transcription? This will wrap up the meeting on Conclave's side.")) {
      return;
    }
    setStopping(true);
    setStopError(null);
    try {
      await bots.stop(live.sessionId);
      onStopped();
    } catch (e) {
      setStopError(e instanceof Error ? e.message : "Failed to stop");
    } finally {
      setStopping(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
        Meet code
      </p>
      <p className="mt-1 font-mono text-sm">{live.sessionId}</p>
      <p className="mt-6 text-xs uppercase tracking-[0.2em] text-muted-foreground">
        Status
      </p>
      <p
        className={
          "mt-1 text-sm font-medium " +
          (isFailure ? "text-destructive" : "text-foreground")
        }
      >
        {humanStatus(live.status)}
      </p>
      <p className="mt-4 text-xs text-muted-foreground">
        {!isTerminal
          ? "Updating every five seconds. You can close this tab — the transcript will land in your dashboard."
          : isFailure
            ? "The bot couldn't join. Most often this is admit-prompt timeout (the meeting host needs to let it in)."
            : "Done. The transcript is processing — it'll appear on your dashboard shortly."}
      </p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link
          href="/dashboard"
          className="inline-flex h-8 items-center rounded-lg border border-border bg-background px-3 text-sm font-medium hover:bg-muted"
        >
          Back to dashboard
        </Link>
        {live.status === "completed" ? (
          <Link
            href={`/meeting/${live.sessionId}`}
            className="inline-flex h-8 items-center rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/80"
          >
            View meeting
          </Link>
        ) : null}
        {!isTerminal ? (
          <button
            onClick={handleStop}
            disabled={stopping}
            className="inline-flex h-8 items-center rounded-lg border border-destructive/40 bg-destructive/10 px-3 text-sm font-medium text-destructive hover:bg-destructive/20 disabled:opacity-50"
          >
            {stopping ? "Stopping…" : "Stop bot"}
          </button>
        ) : null}
      </div>
      {stopError ? (
        <p className="mt-3 text-xs text-destructive">{stopError}</p>
      ) : null}
    </div>
  );
}

function humanStatus(s: BotStatus): string {
  switch (s) {
    case "requested":
      return "Queueing bot…";
    case "joining":
      return "Bot is joining the meeting.";
    case "active":
      return "Recording in progress.";
    case "completed":
      return "Meeting wrapped up.";
    case "failed":
      return "Bot failed to join.";
  }
}
