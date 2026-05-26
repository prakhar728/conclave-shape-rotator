"use client"

import * as React from "react"
import Link from "next/link"
import { List, X } from "@phosphor-icons/react"

import { Laurel } from "@/components/seal-marks"

export interface DrawerLink {
  label: string
  href: string
  numeral?: string
  external?: boolean
}

interface MobileDrawerProps {
  links: DrawerLink[]
  /** Optional CTA pinned to the foot of the drawer. */
  footer?: React.ReactNode
  /** Bracket label shown above the link list. */
  eyebrow?: string
  /** Optional label/title set below the laurel. */
  title?: string
  /** Visually hidden trigger label for screen readers. */
  triggerLabel?: string
}

export function MobileDrawer({
  links,
  footer,
  eyebrow = "INDEX · NAVIGATE THE CHAMBER",
  title = "CONCLAVE",
  triggerLabel = "Open navigation",
}: MobileDrawerProps) {
  const [open, setOpen] = React.useState(false)
  const closeBtnRef = React.useRef<HTMLButtonElement>(null)

  // Lock body scroll while open + close on Escape + focus the close button.
  React.useEffect(() => {
    if (!open) return
    document.body.classList.add("body-locked")
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    closeBtnRef.current?.focus()
    return () => {
      document.body.classList.remove("body-locked")
      window.removeEventListener("keydown", onKey)
    }
  }, [open])

  return (
    <>
      <button
        type="button"
        aria-label={triggerLabel}
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="md:hidden touch-target inline-flex items-center justify-center w-11 h-11 -mr-2 rounded-sm border border-transparent hover:border-border text-foreground transition-colors"
      >
        <List className="size-5" weight="regular" />
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          className="fixed inset-0 z-[100] md:hidden"
        >
          {/* Scrim — porphyry-tinted basalt */}
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
            className="absolute inset-0 scrim-enter"
            style={{ background: "rgba(26, 22, 18, 0.62)" }}
          />

          {/* Codex panel — slides from the right */}
          <aside
            className="codex-panel codex-enter absolute right-0 top-0 bottom-0 w-[88%] max-w-[380px] flex flex-col"
            style={{ paddingTop: "env(safe-area-inset-top)" }}
          >
            <header className="flex items-start justify-between px-6 pt-6 pb-5 border-b border-border">
              <div className="flex items-center gap-3 min-w-0">
                <Laurel className="h-9 w-9 shrink-0" color="#5d2545" />
                <div className="min-w-0">
                  <div className="bracket-label !text-[10px]">SPQR · CONCLAVIUM</div>
                  <div className="font-display text-lg tracking-[0.18em] truncate">{title}</div>
                </div>
              </div>
              <button
                ref={closeBtnRef}
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close navigation"
                className="touch-target inline-flex items-center justify-center w-11 h-11 -mr-2 rounded-sm hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="size-5" />
              </button>
            </header>

            <div className="px-6 pt-6">
              <div className="bracket-label mb-4">{eyebrow}</div>
            </div>

            <nav className="flex-1 overflow-y-auto px-6 pb-6">
              <ul className="space-y-1">
                {links.map((link, i) => {
                  const numeral = link.numeral ?? toRoman(i + 1)
                  const inner = (
                    <span className="flex items-baseline w-full">
                      <span className="font-display text-[11px] tracking-[0.22em] text-[var(--gold)]">{numeral}</span>
                      <span className="leader-dots" aria-hidden />
                      <span className="font-display text-lg uppercase tracking-[0.12em]">
                        {link.label}
                      </span>
                    </span>
                  )
                  const className =
                    "touch-target group flex items-center w-full py-3 border-b border-dashed border-border/70 hover:border-foreground transition-colors"
                  return (
                    <li key={link.href}>
                      {link.external ? (
                        <a
                          href={link.href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={className}
                          onClick={() => setOpen(false)}
                        >
                          {inner}
                        </a>
                      ) : link.href.startsWith("#") ? (
                        <a href={link.href} className={className} onClick={() => setOpen(false)}>
                          {inner}
                        </a>
                      ) : (
                        <Link href={link.href} className={className} onClick={() => setOpen(false)}>
                          {inner}
                        </Link>
                      )}
                    </li>
                  )
                })}
              </ul>
            </nav>

            {footer && (
              <div
                className="border-t border-border px-6 pt-4 pb-6"
                style={{ paddingBottom: "calc(1.5rem + env(safe-area-inset-bottom))" }}
              >
                {footer}
              </div>
            )}
          </aside>
        </div>
      )}
    </>
  )
}

function toRoman(n: number): string {
  const map: [number, string][] = [
    [10, "X"],
    [9, "IX"],
    [5, "V"],
    [4, "IV"],
    [1, "I"],
  ]
  let out = ""
  let v = n
  for (const [val, sym] of map) {
    while (v >= val) {
      out += sym
      v -= val
    }
  }
  return out || "·"
}
