/**
 * Blocking first-login Terms & Conditions gate (Task #18).
 *
 * Mounts once in the root layout, wrapping the whole app. On every
 * authenticated view it checks `auth.me()`; if the current user hasn't
 * accepted the CURRENT terms version (`tnc_needs_acceptance`), it renders a
 * full-screen, non-dismissable overlay with the terms copy and an Accept
 * button. Accepting records acceptance server-side and lets the app through.
 *
 * Deliberately permissive on the unauthenticated path: a 401 (logged out, or
 * on /login) just renders children with no gate — the login flow is unblocked.
 * This is a UI gate, not a server authorization boundary (the server records
 * acceptance but doesn't reject requests), matching the early-access posture.
 */
"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { auth, tnc, type TncStatus } from "@/lib/api";

export function TncGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [copy, setCopy] = useState<TncStatus | null>(null);
  const [needs, setNeeds] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Never gate the auth screens — the user must be able to log in first.
  const skip =
    !!pathname &&
    (pathname.startsWith("/login") || pathname.startsWith("/signup"));

  useEffect(() => {
    if (skip) {
      setNeeds(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const me = await auth.me();
        if (cancelled) return;
        if (me.user.tnc_needs_acceptance) {
          const t = await tnc.get();
          if (cancelled) return;
          setCopy(t);
          setNeeds(true);
        } else {
          setNeeds(false);
        }
      } catch {
        // 401 / not logged in → no gate (pages own their own auth redirects).
        if (!cancelled) setNeeds(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname, skip]);

  async function handleAccept() {
    if (!copy) return;
    setBusy(true);
    setError(null);
    try {
      await tnc.accept(copy.version);
      setNeeds(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record acceptance");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {children}
      {needs && copy ? (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Terms & Conditions"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
        >
          <div className="w-full max-w-lg rounded-lg border border-border bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">Before you continue</h2>
            <pre className="mt-4 max-h-[50vh] overflow-y-auto whitespace-pre-wrap font-sans text-sm text-muted-foreground">
              {copy.text}
            </pre>
            <div className="mt-6 flex items-center justify-end gap-3">
              {error ? (
                <span className="text-xs text-destructive">{error}</span>
              ) : null}
              <button
                onClick={handleAccept}
                disabled={busy}
                className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
              >
                {busy ? "Recording…" : "I accept"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
