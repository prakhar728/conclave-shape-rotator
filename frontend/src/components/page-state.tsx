/**
 * Shared full-page fetch states (UI-NOW.md §3, auth-loading/empty/error
 * P1): every fetch-gated page used to hand-roll a centered "Loading…" /
 * destructive paragraph. One spinner vocabulary instead, so the app feels
 * coherent while it talks to the enclave.
 */
import type { ReactNode } from "react";

/** Ring spinner — quiet, on-brand, no dependency. */
export function Spinner({ className = "size-4" }: { className?: string }) {
  return (
    <span
      className={`inline-block animate-spin rounded-full border-2 border-primary/25 border-t-primary ${className}`}
      aria-hidden
    />
  );
}

export function PageLoading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="flex items-center gap-3">
        <Spinner />
        <p className="text-sm text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}

export function PageError({
  message,
  children,
}: {
  message: string;
  /** Optional extra affordance under the message (e.g. a back link). */
  children?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="text-center">
        <p className="text-sm text-destructive">{message}</p>
        {children}
      </div>
    </div>
  );
}
