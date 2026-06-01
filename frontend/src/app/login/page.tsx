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
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
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
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <Wordmark />
        </div>

        {step === "email" ? (
          <form onSubmit={handleSendOtp} className="flex flex-col gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
                Sign in
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                We&apos;ll email you a six-digit code. New here? Same flow —
                we&apos;ll create your account on first sign in.
              </p>
            </div>
            <Input
              type="email"
              autoComplete="email"
              autoFocus
              required
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={busy}
            />
            <Button type="submit" disabled={busy || !email}>
              {busy ? "Sending…" : "Continue"}
            </Button>
            {error ? (
              <p className="text-xs text-destructive">{error}</p>
            ) : null}
          </form>
        ) : (
          <form onSubmit={handleVerifyOtp} className="flex flex-col gap-4">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
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
  );
}
