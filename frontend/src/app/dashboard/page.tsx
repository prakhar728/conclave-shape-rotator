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
  workspaces,
  type Meeting,
  type MeResponse,
} from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
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
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

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
        </div>

        {meetings === null ? (
          <p className="text-sm text-muted-foreground">Loading meetings…</p>
        ) : meetings.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex flex-col gap-3">
            {meetings.map((m) => (
              <li key={m.session_id}>
                <Link href={`/meeting/${m.session_id}`}>
                  <Card className="transition-colors hover:border-foreground/20">
                    <CardHeader>
                      <CardTitle className="text-base">
                        {m.summary
                          ? truncate(m.summary, 120)
                          : `${m.source} — ${m.date}`}
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-xs text-muted-foreground">
                        {m.date} · {m.source}
                      </p>
                    </CardContent>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}

const EXAMPLE_SESSION_ID = "example-conclave-demo";

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
        <p className="mt-3 text-xs text-muted-foreground">
          Inviting the bot from the dashboard lands in the next phase
          (2.x). For now, take a look at the example below to see what a
          finished card looks like.
        </p>
      </div>
      <div>
        <p className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
          Example meeting
        </p>
        <Link href={`/meeting/${EXAMPLE_SESSION_ID}`}>
          <Card className="transition-colors hover:border-foreground/20">
            <CardHeader>
              <CardTitle className="text-base">
                Walkthrough of how a Conclave meeting card looks once your
                bot has joined a Meet.
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground">
                2026-05-15 · example
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
