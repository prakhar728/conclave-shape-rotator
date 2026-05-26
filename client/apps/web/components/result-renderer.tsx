"use client"

/**
 * Generic result renderer driven by `user_display` hints from the skill card.
 *
 * Two surfaces:
 *  - ResultDetail      participant page — full-size, one result
 *  - FieldCell         admin table — compact cell per column
 *  - ResultExpandedRow admin table — expanded section showing score_table + text fields
 */

import * as React from "react"
import type { DisplayHint, DisplayMap } from "@/lib/types"
import { cn } from "@workspace/ui/lib/utils"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function badgeClasses(value: string): string {
  const v = value.toLowerCase()
  if (["analyzed", "full", "complete", "ok"].includes(v))
    return "text-success bg-success/10 border border-success/30"
  if (["duplicate", "flagged", "error"].includes(v))
    return "text-red-500 bg-red-50 border border-red-200"
  if (["quick", "quick_scored"].includes(v))
    return "text-[#ff9f0a] bg-[#ff9f0a]/10 border border-[#ff9f0a]/30"
  return "text-primary bg-primary/10 border border-primary/30"
}

function gaugePercent(value: unknown, hint: DisplayHint): number {
  const min = hint.min ?? 0
  const max = hint.max ?? 1
  const n = typeof value === "number" ? value : parseFloat(String(value))
  if (isNaN(n)) return 0
  return Math.min(Math.max((n - min) / (max - min), 0), 1)
}

function formatGauge(value: unknown, hint: DisplayHint): string {
  const pct = gaugePercent(value, hint) * 100
  return `${pct.toFixed(0)}`
}

// ---------------------------------------------------------------------------
// Compact cell — used in the admin results table header
// ---------------------------------------------------------------------------

export function FieldCell({
  hint,
  value,
}: {
  hint: DisplayHint
  value: unknown
}) {
  if (value === null || value === undefined) {
    return <span className="text-[#aeaeb2]">—</span>
  }

  switch (hint.type) {
    case "gauge": {
      const pct = gaugePercent(value, hint)
      return (
        <div className="flex items-center gap-2 min-w-[80px]">
          <div className="flex-1 h-1.5 rounded-full bg-[#f5f5f7] overflow-hidden">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${pct * 100}%` }}
            />
          </div>
          <span className="text-sm font-semibold text-[#1d1d1f] tabular-nums w-9 text-right">
            {formatGauge(value, hint)}
          </span>
        </div>
      )
    }
    case "percentile": {
      const n = typeof value === "number" ? value : parseFloat(String(value))
      return (
        <span className="text-sm text-[#1d1d1f]">
          {isNaN(n) ? "—" : `${n.toFixed(0)}th`}
        </span>
      )
    }
    case "badge": {
      const s = String(value)
      return (
        <span className={cn("text-xs font-medium rounded-full px-2.5 py-1", badgeClasses(s))}>
          {s}
        </span>
      )
    }
    case "text": {
      if (!value) return <span className="text-[#aeaeb2]">—</span>
      return <span className="text-sm text-[#6e6e73] truncate max-w-[120px]">{String(value)}</span>
    }
    default:
      return <span className="text-sm text-[#6e6e73]">{String(value)}</span>
  }
}

// ---------------------------------------------------------------------------
// Expanded row content — shown below a table row on click (admin)
// Renders score_table and non-null text fields only (other fields visible in table)
// ---------------------------------------------------------------------------

export function ResultExpandedRow({
  result,
  display,
}: {
  result: Record<string, unknown>
  display: DisplayMap
}) {
  const scoreTables = Object.entries(display).filter(([, h]) => h.type === "score_table")
  const textFields = Object.entries(display).filter(
    ([k, h]) => h.type === "text" && result[k] != null && result[k] !== "",
  )

  if (scoreTables.length === 0 && textFields.length === 0) return null

  return (
    <div className="space-y-4">
      {scoreTables.map(([key, hint]) => {
        const scores = result[key]
        if (!scores || typeof scores !== "object") return null
        return (
          <div key={key}>
            <p className="text-xs font-semibold text-[#6e6e73] uppercase tracking-wider mb-3">
              {hint.label}
            </p>
            <div className="flex flex-wrap gap-6">
              {Object.entries(scores as Record<string, number>).map(([k, v]) => (
                <div key={k} className="min-w-[140px]">
                  <div className="flex justify-between text-sm mb-1.5">
                    <span className="text-[#6e6e73] capitalize">{k}</span>
                    <span className="text-[#1d1d1f] font-medium tabular-nums">{v}/10</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-[#e8e8ed] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary"
                      style={{ width: `${(v / 10) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}

      {textFields.map(([key, hint]) => (
        <div key={key} className="text-sm">
          <span className="text-[#6e6e73] font-medium">{hint.label}: </span>
          <span className="font-mono text-[#1d1d1f]">{String(result[key])}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Full detail view — participant results page
// ---------------------------------------------------------------------------

export function ResultDetail({
  result,
  display,
}: {
  result: Record<string, unknown>
  display: DisplayMap
}) {
  const entries = Object.entries(display)
  const gaugeFields = entries.filter(([, h]) => h.type === "gauge")
  const gridFields = entries.filter(([, h]) => h.type === "percentile" || h.type === "badge")
  const scoreTableFields = entries.filter(([, h]) => h.type === "score_table")
  const textFields = entries.filter(
    ([k, h]) => h.type === "text" && result[k] != null && result[k] !== "",
  )

  return (
    <div className="space-y-4">
      {/* Gauge fields — big centered circles */}
      {gaugeFields.map(([key, hint]) => {
        const pct = gaugePercent(result[key], hint)
        const circumference = 264
        return (
          <div key={key} className="rounded-2xl border border-[#d2d2d7] bg-white p-10 text-center">
            <p className="text-sm text-[#6e6e73] mb-4">{hint.label}</p>
            <div className="relative inline-flex items-center justify-center mb-4">
              <svg className="size-32 -rotate-90" viewBox="0 0 100 100">
                <circle cx="50" cy="50" r="42" fill="none" stroke="#f5f5f7" strokeWidth="6" />
                <circle
                  cx="50" cy="50" r="42" fill="none"
                  stroke="#6e3ff3" strokeWidth="6"
                  strokeDasharray={`${pct * circumference} ${circumference}`}
                  strokeLinecap="round"
                />
              </svg>
              <span className="absolute text-4xl font-bold text-[#1d1d1f] tracking-tight">
                {(pct * 100).toFixed(0)}
              </span>
            </div>
            {/* Show percentile hint below gauge if present */}
            {(() => {
              const pEntry = entries.find(([, h]) => h.type === "percentile")
              if (!pEntry) return null
              const pVal = result[pEntry[0]]
              if (pVal == null) return null
              const n = typeof pVal === "number" ? pVal : parseFloat(String(pVal))
              if (isNaN(n)) return null
              return (
                <p className="text-base text-[#6e6e73]">Top {(100 - n).toFixed(0)}% of submissions</p>
              )
            })()}
          </div>
        )
      })}

      {/* Grid of percentile / badge fields */}
      {gridFields.length > 0 && (
        <div className={cn("grid gap-4", gridFields.length === 1 ? "grid-cols-1" : "grid-cols-2")}>
          {gridFields.map(([key, hint]) => {
            const val = result[key]
            return (
              <div key={key} className="rounded-2xl border border-[#d2d2d7] bg-white p-5 text-center">
                <p className="text-xs text-[#6e6e73] mb-1.5">{hint.label}</p>
                {hint.type === "percentile" ? (
                  <p className="text-3xl font-bold text-[#1d1d1f] tracking-tight">
                    {val != null ? `${typeof val === "number" ? val.toFixed(0) : val}` : "—"}
                    <span className="text-sm text-[#aeaeb2]">th</span>
                  </p>
                ) : (
                  <span className={cn(
                    "inline-block mt-1.5 text-sm font-medium rounded-full px-3 py-1",
                    val != null ? badgeClasses(String(val)) : "text-[#aeaeb2]",
                  )}>
                    {val != null ? String(val) : "—"}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Score table fields */}
      {scoreTableFields.map(([key, hint]) => {
        const scores = result[key]
        if (!scores || typeof scores !== "object") return null
        const entries = Object.entries(scores as Record<string, number>)
        if (entries.length === 0) return null
        return (
          <div key={key} className="rounded-2xl border border-[#d2d2d7] bg-white p-6">
            <p className="text-sm font-semibold text-[#1d1d1f] tracking-tight mb-5">{hint.label}</p>
            <div className="space-y-4">
              {entries.map(([k, v]) => (
                <div key={k}>
                  <div className="flex justify-between text-sm mb-1.5">
                    <span className="text-[#1d1d1f] capitalize">{k}</span>
                    <span className="text-[#6e6e73] font-mono">{v}/10</span>
                  </div>
                  <div className="h-2 rounded-full bg-[#f5f5f7] overflow-hidden">
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${(v / 10) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}

      {/* Text fields (e.g. duplicate_of) */}
      {textFields.map(([key, hint]) => (
        <div key={key} className="rounded-2xl border border-[#d2d2d7] bg-white px-5 py-3.5">
          <p className="text-xs text-[#6e6e73] mb-1">{hint.label}</p>
          <p className="text-sm font-mono text-[#1d1d1f]">{String(result[key])}</p>
        </div>
      ))}
    </div>
  )
}
