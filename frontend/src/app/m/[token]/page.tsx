/**
 * /m/[token] — magic-link landing.
 *
 * Three branches:
 *  - Token invalid / expired: show "this link is no longer valid" + back-home link.
 *  - User signed in AND email matches the token's recipient: consume + push
 *    to /meeting/{id}.
 *  - User signed in BUT email mismatches: show "signed in as X, this link
 *    is for Y" with a sign-out + sign-back-in CTA.
 *  - User not signed in: redirect to /login?email=<recipient>&next=/m/<token>.
 *    /login's existing flow respects ?next= (1.11) and we add an `email=`
 *    pre-fill in 2.10's login-page tweak.
 */
"use client";

import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { Wordmark } from "@/components/wordmark";
import { ApiError, auth, magicLinks } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "invalid" }
  | { kind: "mismatch"; signedInAs: string; recipient: string }
  | { kind: "redirecting" };

export default function MagicLinkPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let link;
      try {
        link = await magicLinks.lookup(token);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setState({ kind: "invalid" });
        } else {
          setState({ kind: "invalid" });
        }
        return;
      }

      // Try to identify the current user.
      let me;
      try {
        me = await auth.me();
      } catch {
        me = null;
      }

      if (cancelled) return;

      if (!me) {
        // Not signed in — bounce to /login with email pre-fill + next.
        const params = new URLSearchParams({
          email: link.user_email,
          next: `/m/${token}`,
        });
        setState({ kind: "redirecting" });
        router.push(`/login?${params.toString()}`);
        return;
      }

      if (me.user.email !== link.user_email) {
        setState({
          kind: "mismatch",
          signedInAs: me.user.email,
          recipient: link.user_email,
        });
        return;
      }

      // Authenticated AND email matches. Consume + go to the meeting.
      try {
        await magicLinks.consume(token);
      } catch {
        // Consume failure is non-fatal — the meeting view will still
        // permission-check via can_user_see.
      }
      if (link.meeting_session_id) {
        setState({ kind: "redirecting" });
        router.push(`/meeting/${link.meeting_session_id}`);
      } else {
        setState({ kind: "redirecting" });
        router.push("/dashboard");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, router]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6">
      <div className="w-full max-w-sm text-center">
        <div className="mb-8 flex justify-center">
          <Wordmark href={null} />
        </div>
        {state.kind === "loading" || state.kind === "redirecting" ? (
          <p className="text-sm text-muted-foreground">Opening your meeting…</p>
        ) : null}
        {state.kind === "invalid" ? (
          <>
            <p className="text-sm font-medium">This link is no longer valid</p>
            <p className="mt-2 text-xs text-muted-foreground">
              The link may have expired (7-day window) or the meeting was
              revoked. Ask the meeting&apos;s owner to send a new one.
            </p>
          </>
        ) : null}
        {state.kind === "mismatch" ? (
          <>
            <p className="text-sm font-medium">Different account</p>
            <p className="mt-2 text-xs text-muted-foreground">
              You&apos;re signed in as <span className="text-foreground">{state.signedInAs}</span>,
              but this link is for{" "}
              <span className="text-foreground">{state.recipient}</span>. Sign
              out and back in with the matching email.
            </p>
            <button
              onClick={async () => {
                try {
                  await auth.logout();
                } finally {
                  const params = new URLSearchParams({
                    email: state.recipient,
                    next: `/m/${token}`,
                  });
                  router.push(`/login?${params.toString()}`);
                }
              }}
              className="mt-4 text-xs text-muted-foreground underline hover:text-foreground"
            >
              Sign out and switch
            </button>
          </>
        ) : null}
      </div>
    </div>
  );
}
