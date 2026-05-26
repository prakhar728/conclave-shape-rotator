"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowRight, Copy, Check } from "@phosphor-icons/react"
import { AttestationWidget } from "@/components/attestation-widget"
import { Laurel, ArchDivider } from "@/components/seal-marks"
import { MobileDrawer } from "@/components/mobile-drawer"

const INSTALL_COMMAND = "npx skills add prakhar728/conclave"

const FORUM_STRIP = [
  "TEE-VERIFIED",
  "INTEL TDX",
  "NIHIL EXPOSITUM",
  "SEALED VERDICTS",
  "ON-CHAIN ATTESTATION",
  "PHALA · BASE · SOLANA",
  "SPQR · CONCLAVIUM",
]

export default function LandingPage() {
  return (
    <div className="min-h-screen arena-bg text-foreground pb-20 md:pb-0">
      <Nav />
      <Hero />
      <ArchDivider />
      <Pathways />
      <HowItWorks />
      <AttestationSection />
      <ForumMarquee />
      <Footer />
      <StickyHerald />
    </div>
  )
}

// ---------------------------------------------------------------------------

function Nav() {
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/85 backdrop-blur-md">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 h-14 flex items-center justify-between gap-3">
        <Link href="/" className="flex items-center gap-2 sm:gap-3 min-w-0">
          <Laurel className="h-6 w-6 sm:h-7 sm:w-7 shrink-0" color="#5d2545" />
          <span className="font-display text-base sm:text-xl tracking-[0.14em] sm:tracking-[0.18em] leading-none truncate">
            CONCLAVE
          </span>
        </Link>

        <nav className="hidden md:flex items-center gap-8 text-sm font-serif">
          <a href="#how-it-works" className="hover:text-primary transition-colors">
            How the games run
          </a>
          <a href="#attestation" className="hover:text-primary transition-colors">
            The Imperial Seal
          </a>
          <a href="#install" className="hover:text-primary transition-colors">
            Enter the lists
          </a>
        </nav>

        <div className="flex items-center gap-1 shrink-0">
          <Link
            href="/setup"
            className="hidden sm:inline-flex rounded-sm border border-primary bg-primary px-4 py-2 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90 transition-colors touch-target-sm items-center"
          >
            + Convene a Conclave
          </Link>
          <MobileDrawer
            title="CONCLAVE"
            eyebrow="INDEX · NAVIGATE THE FORUM"
            links={[
              { label: "How the games run", href: "#how-it-works" },
              { label: "The Imperial Seal", href: "#attestation" },
              { label: "Enter the lists", href: "#install" },
              { label: "Convene a conclave", href: "/setup" },
              { label: "Source on GitHub", href: "https://github.com/prakhar728/conclave", external: true },
            ]}
            footer={
              <Link
                href="/setup"
                className="touch-target inline-flex w-full items-center justify-center gap-2 rounded-sm border border-primary bg-primary px-5 py-3 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                ✦ Convene a Conclave
                <ArrowRight className="size-4" />
              </Link>
            }
          />
        </div>
      </div>
    </header>
  )
}

function StickyHerald() {
  return (
    <div className="md:hidden fixed inset-x-0 bottom-0 z-40 sticky-herald">
      <div className="mx-auto max-w-6xl px-4 py-3 flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="bracket-label !text-[9px] !text-[#8a7a64]">SPQR · CONCLAVIUM</div>
          <div className="font-display text-[11px] tracking-[0.18em] text-[var(--basalt-foreground)] truncate">
            ENTER THE LISTS
          </div>
        </div>
        <Link
          href="/setup"
          className="touch-target inline-flex items-center gap-2 rounded-sm border border-[var(--gold)] bg-[var(--gold)] px-4 py-2.5 text-[11px] font-mono uppercase tracking-wider text-[#2a2018] hover:opacity-90 transition-opacity"
        >
          ✦ Convene
          <ArrowRight className="size-3.5" weight="bold" />
        </Link>
      </div>
    </div>
  )
}

function Hero() {
  return (
    <section className="mx-auto max-w-6xl px-4 sm:px-6 py-12 sm:py-16 lg:py-20">
      <div className="grid lg:grid-cols-[1.15fr_1fr] gap-8 sm:gap-12 items-center">
        <div>
          <div className="bracket-label mb-4">CONFIDENTIAL · TEE-VERIFIED · NOVELTY EVAL</div>
          <h1 className="font-display text-[clamp(2rem,9vw,3rem)] sm:text-5xl xl:text-6xl leading-[0.92] mb-6 tracking-tight">
            <span className="block">SEALED VERDICTS.</span>
            <span className="block">BOUNDED SCORES.</span>
            <span className="block">ZERO EXPOSURE.</span>
          </h1>
          <p className="font-serif text-base sm:text-lg md:text-xl max-w-xl text-foreground/80 mb-8 leading-snug">
            Each idea enters the arena alone. The Conclave deliberates inside
            an Intel TDX enclave — your README, your idea, your code never
            leave your machine in plaintext. Only the verdict comes back, sealed.
          </p>
          <div className="flex flex-col sm:flex-row sm:flex-wrap items-stretch sm:items-center gap-3">
            <a
              href="#install"
              className="touch-target inline-flex items-center justify-center gap-2 rounded-sm border border-primary bg-primary px-5 py-3 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Enter the lists
              <ArrowRight className="size-4" />
            </a>
            <Link
              href="/setup"
              className="touch-target inline-flex items-center justify-center gap-2 rounded-sm border border-border bg-background px-5 py-3 text-xs font-mono uppercase tracking-wider text-foreground hover:border-foreground transition-colors"
            >
              Convene a conclave
            </Link>
          </div>
        </div>

        {/* Arena plate */}
        <figure className="relative">
          <div className="border border-border p-2 bg-background">
            <div className="border border-[var(--gold)]/40 overflow-hidden relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/arena.jpg"
                alt="An imagined Roman arena, banners flying, the lists assembled"
                className="block w-full h-auto"
                style={{ filter: "saturate(0.92) contrast(1.02)" }}
              />
              <div
                className="absolute inset-0 pointer-events-none"
                style={{
                  background:
                    "linear-gradient(180deg, rgba(240,234,216,0.12) 0%, rgba(240,234,216,0) 18%, rgba(240,234,216,0) 82%, rgba(240,234,216,0.18) 100%)",
                }}
              />
            </div>
          </div>
          <figcaption className="flex items-center justify-between mt-3 px-1">
            <span className="bracket-label">THE ARENA · IMAGINED</span>
            <span className="font-serif italic text-xs text-muted-foreground">
              where the lists are read aloud
            </span>
          </figcaption>
        </figure>
      </div>
    </section>
  )
}

function Pathways() {
  return (
    <section id="install" className="mx-auto max-w-6xl px-4 sm:px-6 py-12 sm:py-16">
      <div className="text-center mb-10 sm:mb-12">
        <div className="bracket-label mb-3">TWO PATHS INTO THE ARENA</div>
        <h2 className="font-display text-2xl sm:text-3xl md:text-4xl tracking-wide">CHOOSE YOUR ROLE</h2>
      </div>
      <div className="grid md:grid-cols-2 gap-4 sm:gap-6">
        <ParticipantCard />
        <OperatorCard />
      </div>
    </section>
  )
}

function ParticipantCard() {
  return (
    <div className="paper-card p-6 sm:p-8 space-y-6">
      <div className="space-y-2">
        <div className="bracket-label">FOR GLADIATORS · BUILDERS</div>
        <h2 className="font-display text-2xl tracking-wide uppercase">
          Enter the lists
        </h2>
        <p className="font-serif text-base text-muted-foreground leading-snug">
          Drops into Claude Code, Codex, Cursor, Gemini CLI, Antigravity, and
          GitHub Copilot CLI. Your agent reads your repo locally, encrypts
          to the enclave, and returns your private verdict.
        </p>
      </div>
      <CopyableCommand value={INSTALL_COMMAND} />
      <ul className="space-y-2.5 font-serif text-sm text-foreground/80">
        <li className="flex items-start gap-2.5">
          <span className="text-primary font-display mt-0.5">✦</span>
          Your idea, repo, and README never leave your machine in plaintext.
        </li>
        <li className="flex items-start gap-2.5">
          <span className="text-primary font-display mt-0.5">✦</span>
          Only bounded outputs (your score + faction) leave the chamber.
        </li>
        <li className="flex items-start gap-2.5">
          <span className="text-primary font-display mt-0.5">✦</span>
          Update your submission anytime — only the latest is judged.
        </li>
      </ul>
    </div>
  )
}

function OperatorCard() {
  return (
    <div className="paper-card p-6 sm:p-8 space-y-6">
      <div className="space-y-2">
        <div className="bracket-label">FOR EDITORS · ORGANIZERS</div>
        <h2 className="font-display text-2xl tracking-wide uppercase">
          Convene a conclave
        </h2>
        <p className="font-serif text-base text-muted-foreground leading-snug">
          Configure a hackathon in under a minute: name, end date, cadence,
          and tracks. Get a unique URL to share with participants and a
          dashboard that shows aggregate cohort signals.
        </p>
      </div>
      <Link
        href="/setup"
        className="touch-target inline-flex items-center justify-center sm:justify-start gap-2 rounded-sm border border-primary bg-primary px-5 py-3 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90 transition-colors"
      >
        Establish an instance
        <ArrowRight className="size-4" />
      </Link>
      <ul className="space-y-2.5 font-serif text-sm text-foreground/80">
        <li className="flex items-start gap-2.5">
          <span className="text-primary font-display mt-0.5">✦</span>
          See faction + track distribution, never the raw ideas.
        </li>
        <li className="flex items-start gap-2.5">
          <span className="text-primary font-display mt-0.5">✦</span>
          Periodic deliberation — daily, weekly, or your own cadence.
        </li>
        <li className="flex items-start gap-2.5">
          <span className="text-primary font-display mt-0.5">✦</span>
          Final cohort attestation published on Solana devnet.
        </li>
      </ul>
    </div>
  )
}

function CopyableCommand({ value }: { value: string }) {
  const [copied, setCopied] = React.useState(false)
  async function copy() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1200)
  }
  return (
    <button
      onClick={copy}
      className="group touch-target w-full rounded-sm border border-basalt-border bg-basalt px-4 py-3.5 font-mono text-[13px] sm:text-sm text-basalt-foreground text-left flex items-center justify-between hover:border-primary transition-colors"
      style={{ background: "var(--basalt)", color: "var(--basalt-foreground)", borderColor: "var(--basalt-border)" }}
    >
      <span className="truncate">{value}</span>
      <span
        className="shrink-0 ml-3 transition-colors"
        style={{ color: copied ? "var(--gold)" : "#8a7a64" }}
      >
        {copied ? <Check className="size-4" weight="bold" /> : <Copy className="size-4" />}
      </span>
    </button>
  )
}

function HowItWorks() {
  const acts = [
    {
      n: "I",
      title: "The editor convenes",
      body: "Configure end date, cadence, and tracks. A unique URL goes out to the lists.",
    },
    {
      n: "II",
      title: "Gladiators submit",
      body: "The skill reads the local repo, summarizes, and encrypts to the enclave. Update anytime — same token replaces the prior submission.",
    },
    {
      n: "III",
      title: "The Conclave deliberates",
      body: "On every tick the cohort is judged: novelty against peers, alignment per track, name collisions, faction fit. Only bounded verdicts leave.",
    },
    {
      n: "IV",
      title: "The Imperial Seal lands",
      body: "At end_date the enclave signs the final cohort report and publishes the hash to Solana devnet. Anyone can verify the report came from this enclave.",
    },
  ]
  return (
    <section id="how-it-works" className="basalt-slab py-16 sm:py-20 md:py-24">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="text-center mb-10 sm:mb-12">
          <div className="bracket-label mb-3" style={{ color: "#8a7a64" }}>
            MECHANICS OF THE GAMES
          </div>
          <h2 className="font-display text-3xl sm:text-4xl md:text-5xl tracking-wide" style={{ color: "var(--basalt-foreground)" }}>
            FOUR ACTS, ONE SEAL
          </h2>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-5">
          {acts.map((a) => (
            <div
              key={a.n}
              className="rounded-sm border p-6"
              style={{ borderColor: "var(--basalt-border)", background: "#0f0c09" }}
            >
              <div className="font-display text-4xl mb-3" style={{ color: "#c08a3e" }}>{a.n}</div>
              <div
                className="font-display text-base uppercase tracking-wider mb-3"
                style={{ color: "var(--basalt-foreground)" }}
              >
                {a.title}
              </div>
              <p className="font-serif text-sm leading-snug" style={{ color: "#a99c87" }}>
                {a.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function AttestationSection() {
  return (
    <section id="attestation" className="mx-auto max-w-6xl px-4 sm:px-6 py-16 sm:py-20">
      <div className="text-center mb-10">
        <div className="bracket-label mb-3">VERIFY · DON&apos;T TRUST</div>
        <h2 className="font-display text-2xl sm:text-3xl md:text-4xl tracking-wide uppercase">
          The Imperial Seal
        </h2>
        <p className="font-serif italic text-muted-foreground max-w-xl mx-auto mt-3">
          Every enclave exposes a TDX attestation quote you can verify against
          Phala&apos;s public verifier. Final cohort reports get a matching
          on-chain attestation on Solana devnet.
        </p>
      </div>
      <div className="max-w-2xl mx-auto">
        <AttestationWidget />
      </div>
    </section>
  )
}

function ForumMarquee() {
  return (
    <div className="border-y border-border bg-muted py-3 marquee">
      <div className="marquee-track text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">
        {[...FORUM_STRIP, ...FORUM_STRIP].map((it, i) => (
          <span key={i} className="inline-flex items-center gap-3">
            <span>{it}</span>
            <span aria-hidden style={{ color: "var(--gold)" }}>✦</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function Footer() {
  return (
    <footer>
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-8 sm:py-10 flex flex-col md:flex-row items-center justify-between gap-4 text-center md:text-left">
        <div className="flex items-center gap-3">
          <Laurel className="h-5 w-5" color="#6b5d49" />
          <span className="font-mono text-[11px] sm:text-xs text-muted-foreground uppercase tracking-wider">
            CONCLAVE · confidential hackathon novelty
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 font-serif text-sm">
          <a
            href="https://github.com/prakhar728/conclave"
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            GitHub
          </a>
          <a href="#install" className="text-muted-foreground hover:text-foreground transition-colors">
            Enter the lists
          </a>
          <Link href="/setup" className="text-muted-foreground hover:text-foreground transition-colors">
            Convene
          </Link>
        </div>
      </div>
    </footer>
  )
}
