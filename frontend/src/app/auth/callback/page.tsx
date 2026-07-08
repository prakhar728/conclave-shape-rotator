/**
 * /auth/callback — Supabase OAuth + magic-link landing.
 *
 * Supabase delivers the access token in the URL hash (`#access_token=...`)
 * after a successful OAuth (Google, GitHub, …) or magic-link redirect.
 * The hash isn't sent to the server, so we have to read it client-side,
 * POST it to our backend exchange endpoint, then route to /dashboard
 * (or wherever `?next=` says).
 *
 * Three end states:
 *  - success → full-page replace(next)
 *  - missing token → render "no token" error
 *  - backend rejected → render the upstream error
 */
"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Wordmark } from "@/components/wordmark";
import { ApiError, auth } from "@/lib/api";

export default function AuthCallbackPage() {
  return (
    <Suspense>
      <CallbackInner />
    </Suspense>
  );
}

function CallbackInner() {
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "/dashboard";
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Parse the access_token out of the URL hash.
      if (typeof window === "undefined") return;
      const hash = window.location.hash.startsWith("#")
        ? window.location.hash.slice(1)
        : window.location.hash;
      const params = new URLSearchParams(hash);
      const accessToken = params.get("access_token");
      const errorParam = params.get("error_description") || params.get("error");

      if (errorParam) {
        if (!cancelled) setError(decodeURIComponent(errorParam));
        return;
      }
      if (!accessToken) {
        if (!cancelled) setError("No access token in the redirect URL.");
        return;
      }

      try {
        await auth.exchangeToken(accessToken);
      } catch (e) {
        if (cancelled) return;
        const msg =
          e instanceof ApiError
            ? typeof e.detail === "string"
              ? e.detail
              : `Sign-in failed (HTTP ${e.status})`
            : e instanceof Error
              ? e.message
              : "Sign-in failed";
        setError(msg);
        return;
      }

      if (cancelled) return;
      // Same-origin guard mirroring /login.
      const target = next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
      // Strip the hash so it doesn't linger on the next page.
      window.location.replace(target);
    })();
    return () => {
      cancelled = true;
    };
  }, [next]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6">
      <div className="w-full max-w-sm text-center">
        <div className="mb-8 flex justify-center">
          <Wordmark href={null} />
        </div>
        {error ? (
          <>
            <p className="text-sm font-medium">Sign-in didn&apos;t complete</p>
            <p className="mt-2 text-xs text-muted-foreground">{error}</p>
            <a
              href="/login"
              className="mt-4 inline-block text-xs text-muted-foreground underline hover:text-foreground"
            >
              Try again
            </a>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">Signing you in…</p>
        )}
      </div>
    </div>
  );
}
