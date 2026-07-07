/**
 * /login — Google sign-in.
 *
 * v1 doesn't distinguish signup from login: the OAuth callback upserts the User
 * either way (1.4), so one button handles both. The email + 6-digit-OTP path was
 * removed from the UI (2026-07-07 — Google-only for now); the send-otp / verify-otp
 * backend (auth.sendOtp/verifyOtp) still exists if we want to re-surface it.
 */
"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Wordmark } from "@/components/wordmark";

export default function LoginPage() {
  // useSearchParams must be wrapped in Suspense per Next 15+ rules.
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}

function LoginInner() {
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "/dashboard";

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-vault-atmosphere px-6">
      <div className="w-full max-w-sm">
        {/* Trust cue before login: the wordmark + the one-line pitch. */}
        <div className="mb-8 flex flex-col items-start gap-3">
          <Wordmark size="lg" />
          <p className="text-sm text-muted-foreground">
            Meeting intelligence your provider can&apos;t read.
          </p>
        </div>

        <div className="rounded-none border border-border bg-card p-6">
          <div className="flex flex-col gap-4">
            <div>
              <h1 className="text-2xl font-bold tracking-tight md:text-3xl">
                Sign in
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                New here? Same flow — we&apos;ll create your account on first
                sign in.
              </p>
            </div>

            <GoogleButton next={next} />
          </div>
        </div>
      </div>
    </div>
  );
}


/**
 * Google sign-in button.
 *
 * Redirects to Supabase's OAuth `authorize` URL with provider=google.
 * Supabase handles the Google handshake + redirects back to our
 * `/auth/callback` page with `#access_token=...` in the URL hash.
 *
 * `next` rides along in `redirect_to` so the callback can honor deep links.
 * We base64-encode it into the OAuth state-ish position by passing it as
 * `redirect_to` with a query param the callback re-reads.
 */
function GoogleButton({ next }: { next: string }) {
  // Both env vars are inlined at build time, so server and client see the
  // same string — no SSR hydration mismatch. NEXT_PUBLIC_BASE_URL must
  // match an allow-listed entry in Supabase's Redirect URLs.
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const baseUrl = process.env.NEXT_PUBLIC_BASE_URL;
  if (!supabaseUrl || !baseUrl) return null;
  const callback = `${baseUrl}/auth/callback?next=${encodeURIComponent(next)}`;
  const href =
    `${supabaseUrl}/auth/v1/authorize?provider=google` +
    `&redirect_to=${encodeURIComponent(callback)}`;
  return (
    <a
      href={href}
      className="inline-flex h-10 w-full items-center justify-center gap-3 rounded-none border border-border bg-background px-4 text-sm font-medium hover:bg-muted"
    >
      {/* Google "G" — inline SVG so we don't ship a dependency for one icon. */}
      <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
        <path
          fill="#4285F4"
          d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"
        />
        <path
          fill="#34A853"
          d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.85.86-3.04.86-2.34 0-4.32-1.58-5.02-3.7H.92v2.32A9 9 0 0 0 9 18z"
        />
        <path
          fill="#FBBC05"
          d="M3.98 10.72A5.41 5.41 0 0 1 3.7 9c0-.6.1-1.18.28-1.72V4.96H.92A9 9 0 0 0 0 9c0 1.45.35 2.83.92 4.04l3.06-2.32z"
        />
        <path
          fill="#EA4335"
          d="M9 3.58c1.32 0 2.5.46 3.44 1.35l2.58-2.58A9 9 0 0 0 9 0 9 9 0 0 0 .92 4.96L3.98 7.28C4.68 5.16 6.66 3.58 9 3.58z"
        />
      </svg>
      Continue with Google
    </a>
  );
}
