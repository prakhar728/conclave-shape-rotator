"use client";

import Link from "next/link";
import { ArrowDown } from "lucide-react";

import { Wordmark } from "@/components/wordmark";

export default function Home() {
  return (
    <div className="min-h-screen bg-background text-foreground transition-colors duration-300 font-sans">
      {/* ── Top Navigation ── */}
      <header className="sticky top-0 z-50 w-full border-b border-border bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6 md:px-12">
          <div className="flex items-center gap-2">
            <Wordmark href="/" />
          </div>
          
          <nav className="hidden items-center gap-8 text-xs font-bold tracking-widest uppercase md:flex">
            <a href="#features" className="hover:text-muted-foreground transition-colors">Features</a>
            <a href="#security" className="hover:text-muted-foreground transition-colors">Security</a>
            <a href="#process" className="hover:text-muted-foreground transition-colors">How it works</a>
          </nav>

          <div className="flex items-center gap-6">
            <Link
              href="/login"
              className="text-xs font-bold tracking-widest uppercase border-b border-foreground pb-0.5 hover:text-muted-foreground hover:border-muted-foreground transition-all"
            >
              Record &rarr;
            </Link>
          </div>
        </div>
      </header>

      {/* ── Hero Section ── */}
      <main className="relative overflow-hidden">
        <section className="mx-auto max-w-7xl px-6 py-16 md:px-12 md:py-28">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-12 lg:gap-8">
            
            {/* Left Column: Big Headlines */}
            <div className="lg:col-span-12 flex flex-col justify-between">
              <div>
                {/* Hero headline */}
                <h1 className="font-heading text-4xl font-black leading-[0.9] tracking-tighter text-foreground sm:text-5xl md:text-6xl lg:text-7xl uppercase">
                  Total Recall<br />
                  <span className="text-muted-foreground/30">Zero</span><br />
                  Exposure&reg;
                </h1>
              </div>

              {/* Layout adjustment: paragraph and down arrow side-by-side */}
              <div className="mt-16 flex flex-col gap-8 sm:flex-row sm:items-end justify-between">
                <div className="max-w-md">
                  <p className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                    Conclave &bull; Confidential team memory
                  </p>
                  <p className="text-lg font-medium leading-relaxed text-foreground">
                    Every conversation, whether a meeting bot or a room mic, becomes private, searchable team memory: transcripts, decisions, obligations, a knowledge graph. Processed inside an attested TEE where not even the operator can read it.
                  </p>
                  
                  <div className="mt-8 flex flex-wrap gap-4">
                    <Link
                      href="/login"
                      className="inline-flex h-12 items-center justify-center bg-foreground px-8 text-xs font-bold uppercase tracking-widest text-background transition hover:bg-muted-foreground"
                    >
                      Start for free
                    </Link>
                    <Link
                      href="/meeting/example-conclave-demo"
                      className="inline-flex h-12 items-center justify-center border border-border bg-card px-8 text-xs font-bold uppercase tracking-widest text-foreground transition hover:bg-secondary"
                    >
                      Browse example
                    </Link>
                  </div>
                </div>

                <div className="flex flex-col items-center sm:items-end gap-3 self-start sm:self-auto">
                  <span className="text-xs font-bold tracking-widest uppercase text-muted-foreground">(SCROLL)</span>
                  <div className="flex h-14 w-14 items-center justify-center rounded-none border border-border bg-card transition hover:bg-secondary">
                    <ArrowDown className="h-6 w-6 text-foreground stroke-[2.5]" />
                  </div>
                </div>
              </div>
            </div>

          </div>
        </section>

        {/* ── Section Divider ── */}
        <div className="w-full border-t border-border" />

        {/* ── Showcase & Subtitle section matching Screenshot 2 ── */}
        <section id="features" className="mx-auto max-w-7xl px-6 py-20 md:px-12 md:py-32">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-12 lg:gap-8">
            <div className="lg:col-span-4">
              <h2 className="text-xs font-bold tracking-widest uppercase text-muted-foreground">
                Not a notetaker.
              </h2>
            </div>
            
            <div className="lg:col-span-8">
              <p className="font-heading text-3xl font-bold leading-tight tracking-tight text-foreground sm:text-4xl md:text-5xl">
                Conclave is confidential team memory. It remembers every conversation, turns it into decisions and obligations you can act on, and proves no one outside your team can read a word.
              </p>

              <p className="mt-6 text-base leading-relaxed text-muted-foreground md:text-lg">
                Built for teams that can&apos;t afford a leak: legal, journalism, and anyone handling privileged conversations. Privacy here isn&apos;t a policy; it&apos;s enforced in hardware and verifiable with cryptographic proofs.
              </p>
            </div>
          </div>
        </section>

        {/* ── Cards Grid section matching Screenshot 3 ── */}
        <section className="bg-secondary/40 border-y border-border py-20 md:py-32">
          <div className="mx-auto max-w-7xl px-6 md:px-12">
            <div className="mb-12 flex flex-col md:flex-row md:items-end justify-between gap-4">
              <div>
                <p className="text-xs font-bold tracking-widest uppercase text-muted-foreground mb-2">
                  HOW CONCLAVE WORKS
                </p>
                <h3 className="font-heading text-4xl font-black uppercase tracking-tight sm:text-5xl">
                  Three <span className="text-muted-foreground/35">Layers</span>
                </h3>
              </div>
              <Link
                href="/meeting/example-conclave-demo"
                className="text-xs font-bold tracking-widest uppercase border-b border-foreground pb-0.5 self-start md:self-auto hover:text-muted-foreground hover:border-muted-foreground transition-all"
              >
                Browse an example &rarr;
              </Link>
            </div>

            <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
              {/* Feature 1 */}
              <div className="border border-border bg-card p-8 flex flex-col justify-between transition-transform duration-300 hover:-translate-y-2">
                <div>
                  <div className="mb-6 inline-block rounded-none bg-signal-warn/15 px-3 py-1 text-xs font-bold text-signal-warn tracking-wide uppercase">
                    Capture
                  </div>
                  <h4 className="font-heading text-2xl font-bold uppercase tracking-tight text-foreground mb-4">
                    Record Any Room
                  </h4>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Invite the bot to Google Meet, Teams, or Zoom, or record an in-person meeting from a single mic. Live diarization separates speakers and transcribes as you talk.
                  </p>
                </div>
                <div className="mt-8 border-t border-border pt-4 text-xs font-bold tracking-widest uppercase">
                  01 // CAPTURE
                </div>
              </div>

              {/* Feature 2 */}
              <div className="border border-border bg-card p-8 flex flex-col justify-between transition-transform duration-300 hover:-translate-y-2">
                <div>
                  <div className="mb-6 inline-block rounded-none bg-signal-positive/15 px-3 py-1 text-xs font-bold text-signal-positive tracking-wide uppercase">
                    Intelligence
                  </div>
                  <h4 className="font-heading text-2xl font-bold uppercase tracking-tight text-foreground mb-4">
                    Turn Talk Into Memory
                  </h4>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    An enclave-resident model distills every conversation into a summary, action items, decisions, open questions, and a linked knowledge graph, searchable across all your meetings. Plaintext never leaves the TEE.
                  </p>
                </div>
                <div className="mt-8 border-t border-border pt-4 text-xs font-bold tracking-widest uppercase">
                  02 // INTELLIGENCE
                </div>
              </div>

              {/* Feature 3 */}
              <div className="border border-border bg-card p-8 flex flex-col justify-between transition-transform duration-300 hover:-translate-y-2">
                <div>
                  <div className="mb-6 inline-block rounded-none bg-signal-entity/15 px-3 py-1 text-xs font-bold text-signal-entity tracking-wide uppercase">
                    Trust
                  </div>
                  <h4 className="font-heading text-2xl font-bold uppercase tracking-tight text-foreground mb-4">
                    Own Your Voice
                  </h4>
                  <p className="text-sm leading-relaxed text-muted-foreground">
                    Speakers are recognized only with consent. Voiceprints are user-owned and sealed: hear your clips before you agree, export them anytime, and get a signed proof when they&apos;re deleted.
                  </p>
                </div>
                <div className="mt-8 border-t border-border pt-4 text-xs font-bold tracking-widest uppercase">
                  03 // CONSENT
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── How it works Stepper Section ── */}
        <section id="process" className="mx-auto max-w-7xl px-6 py-20 md:px-12 md:py-32">
          <div className="mb-16 text-center">
            <p className="text-xs font-bold tracking-widest uppercase text-muted-foreground mb-2">
              FROM ROOM TO MEMORY
            </p>
            <h3 className="font-heading text-4xl font-black uppercase tracking-tight sm:text-5xl">
              How It Works
            </h3>
          </div>

          <div className="grid grid-cols-1 gap-8 md:grid-cols-4">
            <div className="relative border-t-4 border-foreground pt-6">
              <span className="font-mono text-xs font-bold text-muted-foreground block mb-2">STAGE 01</span>
              <h4 className="font-heading text-xl font-bold uppercase tracking-tight mb-3">Record</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Invite the bot to a call or record the room. Audio streams over TLS straight into the confidential VM.
              </p>
            </div>
            
            <div className="relative border-t-4 border-foreground pt-6">
              <span className="font-mono text-xs font-bold text-muted-foreground block mb-2">STAGE 02</span>
              <h4 className="font-heading text-xl font-bold uppercase tracking-tight mb-3">Attest</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Intel TDX remote attestation proves the enclave is sealed before a single byte is processed.
              </p>
            </div>

            <div className="relative border-t-4 border-foreground pt-6">
              <span className="font-mono text-xs font-bold text-muted-foreground block mb-2">STAGE 03</span>
              <h4 className="font-heading text-xl font-bold uppercase tracking-tight mb-3">Remember</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                Inside the TEE: diarize, transcribe, and extract decisions, obligations, and a knowledge graph. The model runs only here.
              </p>
            </div>

            <div className="relative border-t-4 border-foreground pt-6">
              <span className="font-mono text-xs font-bold text-muted-foreground block mb-2">STAGE 04</span>
              <h4 className="font-heading text-xl font-bold uppercase tracking-tight mb-3">Control</h4>
              <p className="text-xs text-muted-foreground leading-relaxed">
                You decide who sees what. Share per artifact, export your data, set retention, and prove deletions with signed receipts.
              </p>
            </div>
          </div>
        </section>

        {/* ── Bold CTA section ── */}
        <section className="bg-foreground text-background py-20 md:py-36">
          <div className="mx-auto max-w-5xl px-6 text-center">
            <h2 className="font-heading text-5xl font-black leading-none tracking-tighter sm:text-6xl md:text-7xl uppercase mb-8">
              Record Everything.<br />
              Reveal Nothing.
            </h2>
            <p className="mx-auto max-w-xl text-lg text-background/60 leading-relaxed mb-10">
              The operator provably cannot read your meetings. Trust is enforced by hardware attestation and signed cryptographic proofs, not by our promises.
            </p>
            <Link
              href="/login"
              className="inline-flex h-14 items-center justify-center bg-background px-10 text-xs font-bold uppercase tracking-widest text-foreground transition hover:bg-muted"
            >
              Start for free
            </Link>
          </div>
        </section>
      </main>

      {/* ── Footer matching Screenshot 4 ── */}
      <footer className="bg-foreground text-background border-t border-background/10 py-16">
        <div className="mx-auto max-w-7xl px-6 md:px-12">
          <div className="grid grid-cols-1 gap-12 md:grid-cols-12 md:gap-8 pb-16 border-b border-background/10">
            
            {/* Columns on the left */}
            <div className="md:col-span-8 grid grid-cols-2 gap-8 sm:grid-cols-3">
              <div>
                <h5 className="text-xs font-bold tracking-widest uppercase text-background/40 mb-4">Company</h5>
                <ul className="space-y-2.5 text-sm">
                  <li><Link href="/" className="hover:text-background/80 transition-colors">Home</Link></li>
                  <li><Link href="/meeting/example-conclave-demo" className="hover:text-background/80 transition-colors">Case Study</Link></li>
                  <li><a href="#features" className="hover:text-background/80 transition-colors">Services</a></li>
                  <li><a href="#process" className="hover:text-background/80 transition-colors">Method</a></li>
                </ul>
              </div>

              <div>
                <h5 className="text-xs font-bold tracking-widest uppercase text-background/40 mb-4">Discover</h5>
                <ul className="space-y-2.5 text-sm">
                  <li><Link href="/login" className="hover:text-background/80 transition-colors">Dashboard</Link></li>
                  <li><Link href="/invite" className="hover:text-background/80 transition-colors">Invite Bot</Link></li>
                  <li><Link href="/settings" className="hover:text-background/80 transition-colors">Settings</Link></li>
                  <li><Link href="/graph" className="hover:text-background/80 transition-colors">Graph</Link></li>
                </ul>
              </div>

              <div>
                <h5 className="text-xs font-bold tracking-widest uppercase text-background/40 mb-4">Learn</h5>
                <ul className="space-y-2.5 text-sm">
                  <li><Link href="/obligations" className="hover:text-background/80 transition-colors">Obligations</Link></li>
                  <li><Link href="/search" className="hover:text-background/80 transition-colors">Search Memory</Link></li>
                  <li><Link href="/entities" className="hover:text-background/80 transition-colors">Entities</Link></li>
                  <li><Link href="/calendar" className="hover:text-background/80 transition-colors">Calendar</Link></li>
                </ul>
              </div>
            </div>

            {/* Email Form on the right */}
            <div className="md:col-span-4 flex flex-col justify-between">
              <div>
                <h5 className="text-xs font-bold tracking-widest uppercase text-background/40 mb-3">Newsletter</h5>
                <p className="text-sm text-background/70 mb-6 leading-relaxed">
                  Get valuable strategy, culture, and security insights straight to your inbox.
                </p>
                <form className="relative border-b border-background/20 pb-2 flex items-center justify-between">
                  <input
                    type="email"
                    placeholder="Your email here"
                    className="bg-transparent text-sm text-background placeholder-background/40 outline-none w-full pr-10"
                    required
                  />
                  <button type="submit" className="text-background hover:text-background/80 absolute right-0">
                    &rarr;
                  </button>
                </form>
              </div>
            </div>

          </div>

          {/* Bottom row */}
          <div className="mt-12 flex flex-col gap-6 sm:flex-row sm:items-center sm:justify-between text-xs text-background/50">
            <div>
              &copy; 2005-2026 Conclave&reg; | Intel VM attested | Privacy guaranteed
            </div>
            <div className="flex gap-6">
              <a href="#" className="hover:text-background/80 transition-colors">Twitter</a>
              <a href="#" className="hover:text-background/80 transition-colors">GitHub</a>
              <a href="#" className="hover:text-background/80 transition-colors">LinkedIn</a>
              <a href="#" className="hover:text-background/80 scroll-smooth" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>
                Back to top &uarr;
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

