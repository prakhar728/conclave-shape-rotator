/**
 * Settings section: the current Terms & Conditions copy (Task #18).
 *
 * The same copy the blocking first-login gate shows, mirrored in Settings so a
 * user who already accepted can re-read the terms (and see when they accepted).
 */
"use client";

import { useEffect, useState } from "react";

import { tnc, type TncStatus } from "@/lib/api";

export function TncNotice() {
  const [t, setT] = useState<TncStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    tnc
      .get()
      .then((r) => !cancelled && setT(r))
      .catch(() => {
        /* non-critical settings panel — silently omit on error */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!t) return null;

  return (
    <section className="mt-8 rounded-lg border border-border bg-card p-5">
      <h2 className="text-sm font-medium">Terms &amp; Conditions</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Version <span className="font-mono">{t.version}</span>
        {t.accepted_at ? ` · accepted ${t.accepted_at}` : " · not yet accepted"}
      </p>
      <pre className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap font-sans text-xs text-muted-foreground">
        {t.text}
      </pre>
    </section>
  );
}
