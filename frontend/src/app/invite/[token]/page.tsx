/**
 * /invite/[token] — accept a workspace invitation (Task #32).
 *
 * The invite email links here. An already-signed-in recipient accepts in one
 * click and lands in the workspace. If they're not signed in, the accept 401s and
 * we send them to /login (an invitee who signs up fresh is auto-accepted on
 * sign-in anyway, so either path lands them in the workspace).
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { PageError, PageLoading } from "@/components/page-state";
import { ApiError, workspaces, type Workspace } from "@/lib/api";

export default function AcceptInvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const router = useRouter();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await workspaces.acceptInvite(token);
        if (cancelled) return;
        setWorkspace(r.workspace);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setError("This invite is invalid or was already used.");
          return;
        }
        setError(err instanceof Error ? err.message : "Couldn't accept the invite");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, router]);

  if (error) {
    return (
      <PageError message={error}>
        <Link
          href="/dashboard"
          className="mt-3 inline-block text-xs text-muted-foreground hover:text-foreground"
        >
          Go to dashboard
        </Link>
      </PageError>
    );
  }
  if (!workspace) return <PageLoading />;

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center px-6 text-center">
      <h1 className="text-2xl font-bold tracking-tight">
        You&apos;ve joined {workspace.name}
      </h1>
      <p className="mt-2 text-sm text-muted-foreground">
        You can now see the meetings shared with you in this workspace.
      </p>
      <Link
        href={`/workspace/${workspace.id}`}
        className="mt-6 inline-block rounded-none bg-foreground px-4 py-2 text-sm font-medium text-background"
      >
        Open workspace
      </Link>
    </main>
  );
}
