/**
 * /login — email + OTP entry.
 *
 * v1 doesn't distinguish signup from login. `verify-otp` upserts the User
 * either way (1.4), so the same flow handles both cases. The `/signup`
 * route exists as a redirect for marketing-link compatibility.
 *
 * State machine:
 *   email-entry   → user types email, clicks Continue
 *   send pending  → POST /api/auth/v1/send-otp; on success → otp-entry
 *   otp-entry     → user types 6-digit code, clicks Sign in
 *   verify pending → POST /api/auth/v1/verify-otp; on success → /dashboard
 *   error         → inline message, return to previous step
 */
"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AttestedBadge } from "@/components/attested-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Wordmark } from "@/components/wordmark";
import { auth } from "@/lib/api";

type Step = "email" | "otp";

export default function LoginPage() {
  // useSearchParams must be wrapped in Suspense per Next 15+ rules.
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}

function LoginInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = searchParams.get("next") || "/dashboard";
  const prefillEmail = searchParams.get("email") || "";
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState(prefillEmail);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSendOtp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await auth.sendOtp(email.trim());
      setStep("otp");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send code");
    } finally {
      setBusy(false);
    }
  }

  async function handleVerifyOtp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await auth.verifyOtp(email.trim(), otp.trim());
      // Sanity-check `next` so a crafted URL can't push to an external
      // origin; only same-origin paths are honored.
      const target = next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
      router.push(target);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid code");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-vault-atmosphere px-6">
      <div className="w-full max-w-sm">
        {/* Trust cue before login: the wordmark + attested badge + the
            one-line pitch. A prospect should know what's different here
            before they type anything. */}
        <div className="mb-8 flex flex-col items-start gap-3">
          <div className="flex items-baseline gap-3">
            <Wordmark size="lg" />
            <AttestedBadge />
          </div>
          <p className="font-heading text-lg italic text-muted-foreground">
            Meeting intelligence your provider can&apos;t read.
          </p>
        </div>

        <div className="rounded-xl border border-border bg-card p-6 shadow-lg shadow-black/20">
        {step === "email" ? (
          <div className="flex flex-col gap-4">
            <div>
              <h1 className="font-heading text-3xl tracking-tight">
                Sign in
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                New here? Same flow — we&apos;ll create your account on first
                sign in.
              </p>
            </div>

            <GoogleButton next={next} />

            <div className="flex items-center gap-3 py-1">
              <span className="h-px flex-1 bg-border" />
              <span className="text-xs text-muted-foreground">or email</span>
              <span className="h-px flex-1 bg-border" />
            </div>

            <form onSubmit={handleSendOtp} className="flex flex-col gap-3">
              <Input
                type="email"
                autoComplete="email"
                required
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={busy}
              />
              <Button type="submit" disabled={busy || !email}>
                {busy ? "Sending…" : "Send 6-digit code"}
              </Button>
            </form>

            {error ? <p className="text-xs text-destructive">{error}</p> : null}
          </div>
        ) : (
          <form onSubmit={handleVerifyOtp} className="flex flex-col gap-4">
            <div>
              <h1 className="font-heading text-3xl tracking-tight">
                Enter the code
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Sent to <span className="text-foreground">{email}</span>.
                Check your spam folder if it doesn&apos;t arrive in a minute.
              </p>
            </div>
            <Input
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              required
              maxLength={6}
              placeholder="123456"
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
              disabled={busy}
            />
            <Button type="submit" disabled={busy || otp.length !== 6}>
              {busy ? "Verifying…" : "Sign in"}
            </Button>
            <button
              type="button"
              onClick={() => {
                setStep("email");
                setOtp("");
                setError(null);
              }}
              className="text-xs text-muted-foreground hover:text-foreground"
              disabled={busy}
            >
              Use a different email
            </button>
            {error ? (
              <p className="text-xs text-destructive">{error}</p>
            ) : null}
          </form>
        )}
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
      className="inline-flex h-10 w-full items-center justify-center gap-3 rounded-lg border border-border bg-background px-4 text-sm font-medium hover:bg-muted"
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
