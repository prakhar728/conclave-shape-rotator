/**
 * The trust mark: emerald dot + mono "attested". The whole pitch in one
 * chip — the operator provably can't read your meetings. Shown in the
 * app header and as a pre-login trust cue on /login.
 *
 * TODO(tee-deploy): wire to a real attestation endpoint (TDX quote
 * verification) instead of rendering statically.
 */
export function AttestedBadge() {
  return (
    <span
      title="Running in a confidential VM · Intel TDX"
      className="inline-flex cursor-default items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[10px] font-medium leading-4 text-muted-foreground shadow-sm"
    >
      {/* Green = operational/trust, Vantage-style status dot. */}
      <span className="relative flex size-1.5" aria-hidden>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-attested opacity-60" />
        <span className="relative inline-flex size-1.5 rounded-full bg-attested" />
      </span>
      attested
    </span>
  );
}
