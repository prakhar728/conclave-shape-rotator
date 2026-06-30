/**
 * /feedback — in-app feedback / feature-request page (Task #19).
 *
 * Session-authed. Captures the route the user came from (the `?from=` param the
 * nav link sets, falling back to document.referrer) as page-context, so the team
 * sees where the feedback was triggered. The form posts to /api/feedback.
 */
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { FeedbackForm } from "@/components/feedback-form";
import { PageError, PageLoading } from "@/components/page-state";
import { ApiError, auth, type MeResponse } from "@/lib/api";

function sameOriginPath(referrer: string): string | null {
  // Only keep a same-origin referrer, and only its path — never a full URL with
  // another origin (privacy) — so page-context stays a clean internal route.
  try {
    const url = new URL(referrer);
    if (typeof window !== "undefined" && url.origin !== window.location.origin) {
      return null;
    }
    return url.pathname + url.search;
  } catch {
    return null;
  }
}

export default function FeedbackPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pageContext, setPageContext] = useState<string | null>(null);

  useEffect(() => {
    // Resolve page-context client-side (avoids useSearchParams Suspense rules):
    // prefer the explicit ?from= the nav link passes, else a same-origin referrer.
    const fromParam = new URLSearchParams(window.location.search).get("from");
    if (fromParam) {
      setPageContext(fromParam);
    } else if (document.referrer) {
      setPageContext(sameOriginPath(document.referrer));
    }
  }, []);

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
      <main className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="text-2xl font-bold tracking-tight">Feedback</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Tell us what to build next, or report something broken. It goes
          straight to the team.
        </p>
        <div className="mt-8">
          <FeedbackForm
            pageContext={pageContext}
            workspaceId={me.workspace?.id ?? null}
          />
        </div>
      </main>
    </AppShell>
  );
}
