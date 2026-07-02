/**
 * /admin/feedback — admin-only feedback inbox (Task #19).
 *
 * The operator-blind read path for the TEE: an admin (CONCLAVE_ADMIN_EMAILS,
 * enforced server-side) reads submitted feedback over the authenticated API
 * rather than a DB shell into the enclave. Non-admins get a forbidden notice
 * (the inbox component handles the 403); the nav entry only shows for admins.
 */
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { FeedbackInbox } from "@/components/feedback-inbox";
import { PageError, PageLoading } from "@/components/page-state";
import { ApiError, auth, type MeResponse } from "@/lib/api";

export default function AdminFeedbackPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
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

  if (error && !me) return <PageError message={error} />;
  if (!me) return <PageLoading />;

  return (
    <AppShell user={me.user}>
      <main className="w-full px-6 py-10 md:px-8">
        <h1 className="text-2xl font-bold tracking-tight">Feedback inbox</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Submissions from the in-app feedback page, newest first.
        </p>
        <div className="mt-8">
          <FeedbackInbox />
        </div>
      </main>
    </AppShell>
  );
}
