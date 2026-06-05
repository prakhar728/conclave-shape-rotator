/**
 * /questions — Open Questions Board (Phase 3, BUILD_DOC §4 D-3b).
 *
 * Workspace-wide list of every `open_question` signal across meetings,
 * newest meeting first. Each row links to the source meeting.
 *
 * v1 scope (per BUILD_DOC §8 row 3.5): read-only. No resolve UX. If
 * dogfooding shows we want it, v1.5 adds the state machine + write path.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { PageError, PageLoading } from "@/components/page-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  auth,
  workspaces,
  type MeResponse,
  type OpenQuestion,
} from "@/lib/api";

export default function QuestionsPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [questions, setQuestions] = useState<OpenQuestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
        if (!meResp.workspace) {
          setQuestions([]);
          return;
        }
        const q = await workspaces.openQuestions(meResp.workspace.id);
        if (!cancelled) setQuestions(q.questions);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (error) return <PageError message={error} />;
  if (!me) return <PageLoading />;

  return (
    <div className="min-h-screen bg-background">
      <AppHeader user={me.user} workspace={me.workspace} />
      <main className="mx-auto max-w-3xl px-6 py-10">
        <div className="mb-8">
          <h1 className="font-heading text-4xl tracking-tight">
            Open questions
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {questions === null
              ? "Loading…"
              : questions.length === 0
                ? "Across all your meetings."
                : `${questions.length} unresolved across all your meetings.`}
          </p>
        </div>

        {questions === null ? (
          <p className="text-sm text-muted-foreground">Loading questions…</p>
        ) : questions.length === 0 ? (
          <EmptyState hasWorkspace={Boolean(me.workspace)} />
        ) : (
          <ul className="flex flex-col gap-3">
            {questions.map((q, idx) => (
              <li key={`${q.meeting.session_id}-${idx}`}>
                <Link href={`/meeting/${q.meeting.session_id}`}>
                  <Card className="transition-colors hover:border-foreground/20">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-base font-medium">
                        {q.text}
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        {q.said_by.length > 0 ? (
                          <>
                            {q.said_by.map((name) => (
                              <span
                                key={name}
                                className="rounded-full border border-border px-2 py-0.5 text-foreground"
                              >
                                {name}
                              </span>
                            ))}
                            <span>·</span>
                          </>
                        ) : null}
                        <span>{q.meeting.date}</span>
                        <span>·</span>
                        <span className="truncate">
                          {q.meeting.summary
                            ? truncate(q.meeting.summary, 60)
                            : q.meeting.source}
                        </span>
                      </div>
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

function EmptyState({ hasWorkspace }: { hasWorkspace: boolean }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-10 text-center">
      <p className="text-sm font-medium">You&apos;re all caught up</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {hasWorkspace
          ? "No open questions across your meetings. New ones land here as the bot processes future meetings."
          : "Sign in to a workspace to see questions across your meetings."}
      </p>
    </div>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
