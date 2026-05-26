"use client"

import * as React from "react"
import { Copy, Check, CaretDown, CircleNotch } from "@phosphor-icons/react"
import { cn } from "@workspace/ui/lib/utils"
import { Laurel, SpqrSeal } from "@/components/seal-marks"
import { api, ApiError } from "@/lib/api"

interface AttestationWidgetProps {
  compact?: boolean
  onVerified?: () => void
  className?: string
}

type AttState = "idle" | "loading" | "verified" | "failed"

// Build-time identifiers — set in Vercel project env (or .env.production.local
// for local prod builds). NEXT_PUBLIC_BUILD_SHA is the git SHA the bundle was
// built from; NEXT_PUBLIC_IMAGE_DIGEST is the docker manifest digest of the
// CVM image. Defaults to "unknown" when unset so we never silently lie.
const BUILD_SHA = process.env.NEXT_PUBLIC_BUILD_SHA || "unknown"
const IMAGE_DIGEST = process.env.NEXT_PUBLIC_IMAGE_DIGEST || "unknown"

export function AttestationWidget({ compact, onVerified, className }: AttestationWidgetProps) {
  const [state, setState] = React.useState<AttState>("idle")
  const [expanded, setExpanded] = React.useState(false)
  const [quote, setQuote] = React.useState<string | null>(null)
  const [verifyUrl, setVerifyUrl] = React.useState<string | null>(null)
  const [errorMsg, setErrorMsg] = React.useState<string | null>(null)

  async function verify() {
    setState("loading")
    setErrorMsg(null)
    try {
      const resp = await api.attestation()
      // The backend returns a stub when not running in TEE or when the dstack
      // agent is unreachable. Treat those as failures so we don't render
      // theater as if it were real.
      if (!resp.quote || resp.quote.startsWith("stub_")) {
        setQuote(resp.quote || "")
        setVerifyUrl(resp.verify_url || null)
        setErrorMsg(
          resp.quote === "stub_attestation_quote_not_in_tee"
            ? "Backend reports IN_TEE=false. This deployment is not running inside a TDX enclave."
            : resp.quote === "stub_attestation_quote_dstack_unreachable"
              ? "TDX enclave is up but the dstack agent is unreachable from the app container."
              : "Attestation endpoint returned a stub. Verify the deployment.",
        )
        setState("failed")
        return
      }
      setQuote(resp.quote)
      setVerifyUrl(resp.verify_url || null)
      setState("verified")
      // Hold the verified state visible for a beat so the seal-stamp animation
      // paints before the parent swaps this widget for the next step.
      setTimeout(() => onVerified?.(), 1200)
    } catch (e) {
      setErrorMsg(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
      setState("failed")
    }
  }

  // First 64 hex chars of the live quote — a deterministic fingerprint of
  // *this* attestation. Not the TDX MRTD, but honest: it's derived from real
  // bytes the enclave just signed. Header strip so we display the meaningful
  // body of the hex blob.
  const measurementDisplay = quote && quote.length >= 64
    ? quote.replace(/^0x/, "").slice(0, 64)
    : "—"

  return (
    <div
      className={cn(
        "rounded-sm border bg-background p-6 transition-all",
        state === "verified" ? "border-primary" : "border-border",
        className,
      )}
    >
      {!compact && (
        <div className="mb-5 flex items-start gap-4">
          {/* Seal slot — switches glyph by state */}
          <div className="shrink-0 w-20 h-20 flex items-center justify-center">
            {state === "idle" && (
              <div className="w-20 h-20 rounded-full border-2 border-dashed border-border flex items-center justify-center text-2xl text-muted-foreground">
                ◯
              </div>
            )}
            {state === "loading" && (
              <div className="w-20 h-20 rounded-full border-2 border-primary flex items-center justify-center text-primary animate-pulse">
                <Laurel className="h-12 w-12" color="#5d2545" />
              </div>
            )}
            {(state === "verified" || state === "failed") && (
              <div className={cn(state === "verified" && "seal-stamp")}>
                <SpqrSeal className="h-20 w-20" />
              </div>
            )}
          </div>

          <div className="flex-1 min-w-0">
            <div className="bracket-label mb-1">
              {state === "idle" && "UNSEALED · AWAITING VERIFICATION"}
              {state === "loading" && "VERIFYING · TDX QUOTE IN FLIGHT"}
              {state === "verified" && "SEALED · IMPERIAL VERIFICATION COMPLETE"}
              {state === "failed" && "BROKEN SEAL · MEASUREMENT MISMATCH"}
            </div>
            <h3 className="font-display text-xl tracking-wide uppercase mb-1">
              The Imperial Seal
            </h3>
            <p className="font-serif italic text-sm text-muted-foreground leading-snug">
              The Conclave deliberates in private. The seal proves it convened —
              nobody can recover what was said. Verify before entering the lists.
            </p>
          </div>
        </div>
      )}

      {/* Inscribed inscription rows */}
      <div className="rounded-sm border border-border bg-muted/40 p-4 space-y-3">
        <DataRow label="Measurement" value={measurementDisplay} truncate />
        <DataRow label="Image digest" value={IMAGE_DIGEST} />
        <DataRow label="Git SHA" value={BUILD_SHA} />
      </div>

      <div className="mt-5 flex items-center gap-3">
        {state === "idle" && (
          <button
            onClick={verify}
            className="rounded-sm border border-primary bg-primary px-5 py-2.5 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90"
          >
            ✦ Verify the Seal
          </button>
        )}
        {state === "loading" && (
          <div className="flex items-center gap-2 text-sm font-serif italic text-muted-foreground">
            <CircleNotch className="size-4 animate-spin" />
            Reading the quote…
          </div>
        )}
        {state === "verified" && (
          <div className="flex items-center gap-2 text-sm font-serif text-primary">
            <Laurel className="size-5" color="#5d2545" />
            <span className="uppercase font-mono text-xs tracking-wider">
              Sealed by SPQR · Conclavium
            </span>
            {verifyUrl && (
              <a
                href={verifyUrl}
                target="_blank"
                rel="noreferrer"
                className="ml-2 underline-offset-4 hover:underline text-xs font-mono"
              >
                verify on Phala →
              </a>
            )}
          </div>
        )}
        {state === "failed" && (
          <div
            className="text-sm font-serif italic flex flex-col gap-1"
            style={{ color: "#8b2317" }}
          >
            <span>The seal is broken — verification did not succeed.</span>
            {errorMsg && (
              <span className="text-xs font-mono not-italic opacity-80">{errorMsg}</span>
            )}
            <button
              onClick={verify}
              className="self-start mt-1 text-xs font-mono uppercase tracking-wider underline-offset-4 hover:underline"
            >
              retry verification
            </button>
          </div>
        )}
      </div>

      {!compact && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-4 flex items-center gap-1 text-[11px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
        >
          <CaretDown
            className={cn("size-3 transition-transform", expanded && "rotate-180")}
          />
          {expanded ? "Conceal" : "Reveal"} the raw TDX quote
        </button>
      )}

      {expanded && (
        <pre className="mt-3 rounded-sm bg-muted p-4 text-xs font-mono text-foreground overflow-x-auto leading-relaxed border border-border whitespace-pre-wrap break-all">
          {quote ?? "Verify the seal to fetch the live TDX quote."}
        </pre>
      )}
    </div>
  )
}

function DataRow({
  label,
  value,
  truncate,
}: {
  label: string
  value: string
  truncate?: boolean
}) {
  const [copied, setCopied] = React.useState(false)

  return (
    <div className="flex items-center justify-between gap-4">
      <span className="bracket-label shrink-0 normal-case">{label}</span>
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={cn(
            "text-xs font-mono text-foreground bg-background px-2 py-0.5 rounded-sm border border-border",
            truncate && "truncate max-w-[260px]",
          )}
        >
          {value}
        </span>
        <button
          onClick={async () => {
            await navigator.clipboard.writeText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
          className="text-muted-foreground hover:text-foreground transition-colors shrink-0"
          title="Copy"
        >
          {copied ? (
            <Check className="size-3 text-primary" />
          ) : (
            <Copy className="size-3" />
          )}
        </button>
      </div>
    </div>
  )
}
