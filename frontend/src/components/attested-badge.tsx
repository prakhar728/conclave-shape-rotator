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
      className="inline-flex cursor-default items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-mono text-[10px] leading-4 text-primary"
    >
      <span className="size-1.5 rounded-full bg-attested" aria-hidden />
      attested
    </span>
  );
}
