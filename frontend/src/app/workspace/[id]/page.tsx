/**
 * /workspace/[id] — workspace detail.
 *
 * In v1 every user has exactly one workspace ("Personal"), so this URL is
 * mostly URL-form for v1.5 multi-workspace nav. Currently it shows the
 * same meetings list /dashboard does, scoped to the URL-param workspace.
 *
 * Non-members get 404 from the backend; we surface that as a clean message
 * rather than the generic error.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { PageError, PageLoading } from "@/components/page-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ApiError,
  auth,
  workspaces,
  type Meeting,
  type MeResponse,
  type Workspace,
} from "@/lib/api";

export default function WorkspacePage({
  params,
}: {
  // Next 15+ ships params as a Promise; React's `use()` unwraps it.
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [meResp, wsResp, mResp] = await Promise.all([
          auth.me(),
          workspaces.get(id),
          workspaces.meetings(id),
        ]);
        if (cancelled) return;
        setMe(meResp);
        setWorkspace({ ...wsResp.workspace, role: wsResp.role });
        setMeetings(mResp.meetings);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setError("Workspace not found or you don't have access.");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load");
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
  if (!me || !workspace || meetings === null) return <PageLoading />;

  return (
    <div className="min-h-screen bg-background">
      <AppHeader user={me.user} workspace={workspace} />
      <main className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-8">
          <h1 className="text-3xl font-semibold tracking-tight">
            {workspace.name}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {meetings.length} meeting{meetings.length === 1 ? "" : "s"} ·{" "}
            <span className="capitalize">{workspace.role}</span>
          </p>
        </div>

        {meetings.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center">
            <p className="text-sm font-medium">No meetings yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Invite the Conclave bot to your next Meet to see it here.
            </p>
          </div>
        ) : (
          <ul className="flex flex-col gap-3">
            {meetings.map((m) => (
              <li key={m.session_id}>
                <Link href={`/meeting/${m.session_id}`}>
                  <Card className="transition-colors hover:border-foreground/20">
                    <CardHeader>
                      <CardTitle className="text-base">
                        {m.summary
                          ? m.summary.length > 120
                            ? `${m.summary.slice(0, 119)}…`
                            : m.summary
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
