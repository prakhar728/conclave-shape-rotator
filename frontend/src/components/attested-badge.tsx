/**
 * The trust mark: a live attestation chip. Queries the backend's TDX
 * attestation endpoint and renders HONESTLY — a pulsing green "attested" only
 * when a real hardware quote comes back; otherwise amber "local · unattested"
 * (running outside a TEE, e.g. local dev, or the dstack agent is unreachable).
 * Shown in the app header and as a pre-login trust cue on /login.
 */
"use client";

import { useEffect, useState } from "react";

import { attestation, isAttested, type Attestation } from "@/lib/api";

export function AttestedBadge() {
  const [att, setAtt] = useState<Attestation | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    attestation
      .get()
      .then((a) => !cancelled && setAtt(a))
      .catch(() => {})
      .finally(() => !cancelled && setLoaded(true));
    return () => {
      cancelled = true;
    };
  }, []);

  const attested = isAttested(att);
  const label = !loaded ? "checking…" : attested ? "attested" : "local · unattested";
  const title = attested
    ? "Running in a confidential VM · Intel TDX (hardware-attested)"
    : "Local / development — NOT running in an attested TEE";

  return (
    <span
      title={title}
      className="inline-flex cursor-default items-center gap-1.5 rounded-none border border-border bg-card px-2.5 py-1 text-[10px] font-medium leading-4 text-muted-foreground"
    >
      <span className="relative flex size-1.5" aria-hidden>
        {attested ? (
          <>
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-attested opacity-60" />
            <span className="relative inline-flex size-1.5 rounded-full bg-attested" />
          </>
        ) : (
          <span
            className={`relative inline-flex size-1.5 rounded-full ${loaded ? "bg-signal-warn" : "bg-muted-foreground"}`}
          />
        )}
      </span>
      {label}
    </span>
  );
}
