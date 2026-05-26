"use client"

import * as React from "react"
import { ShieldCheck, Copy, Check } from "@phosphor-icons/react"
import { cn } from "@workspace/ui/lib/utils"

interface EnclaveSigBadgeProps {
  signature: string
  verifyUrl?: string
  className?: string
}

export function EnclaveSigBadge({ signature, verifyUrl, className }: EnclaveSigBadgeProps) {
  const [copied, setCopied] = React.useState(false)
  const truncated = signature.length > 24 ? `${signature.slice(0, 12)}…${signature.slice(-12)}` : signature

  return (
    <div
      className={cn(
        "inline-flex items-center gap-3 rounded-xl border border-[#d2d2d7] bg-[#f5f5f7] px-4 py-2.5",
        className,
      )}
    >
      <ShieldCheck weight="fill" className="size-4 text-success shrink-0" />
      <span className="font-mono text-xs text-[#1d1d1f]" title={signature}>
        {truncated}
      </span>
      <button
        onClick={async () => {
          await navigator.clipboard.writeText(signature)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        }}
        className="text-[#aeaeb2] hover:text-[#6e6e73] transition-colors shrink-0"
      >
        {copied ? <Check className="size-3 text-success" /> : <Copy className="size-3" />}
      </button>
      {verifyUrl && (
        <a
          href={verifyUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs font-medium text-primary hover:text-[#5a2fd4] transition-colors shrink-0"
        >
          Verify →
        </a>
      )}
    </div>
  )
}
