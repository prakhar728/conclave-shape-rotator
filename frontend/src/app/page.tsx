/**
 * Public landing page — Vantage language (user-supplied reference,
 * 2026-06-04): floating dark pill nav, ping-dot badge, oversized serif
 * headline with an italic muted accent, pill CTAs, and a dark
 * rounded-slab closing CTA. All color through theme tokens.
 */
import Link from "next/link";

import { AttestedBadge } from "@/components/attested-badge";
import { Wordmark } from "@/components/wordmark";

export default function Home() {
  return (
    <div className="min-h-screen bg-vault-atmosphere">
      {/* ── Floating dark pill nav ── */}
      <header className="fixed left-1/2 top-6 z-50 w-full max-w-4xl -translate-x-1/2 px-6">
        <nav className="flex h-16 items-center justify-between rounded-full border border-card/10 bg-foreground/95 px-3 shadow-2xl backdrop-blur-xl">
          <div className="pl-2">
            <Wordmark inverted href="/" />
          </div>
          <div className="flex items-center gap-3 pr-1">
            <span className="hidden sm:block">
              <AttestedBadge />
            </span>
            <Link
              href="/login"
              className="rounded-full bg-primary px-5 py-2.5 text-sm font-bold text-primary-foreground shadow-xl shadow-primary/20 transition-all hover:bg-card hover:text-primary active:scale-95"
            >
              Sign in
            </Link>
          </div>
        </nav>
      </header>

      {/* ── Hero ── */}
      <main className="flex min-h-screen flex-col items-center justify-center px-6 pt-28 text-center">
        <div className="mx-auto max-w-3xl">
          {/* Badge */}
          <div className="mb-8 inline-flex cursor-default items-center gap-2 rounded-full border border-border bg-card px-4 py-2 shadow-sm">
            <span className="relative flex h-2 w-2" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-attested opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-attested" />
            </span>
            <span className="text-sm font-medium text-muted-foreground">
              Running in a confidential VM · Intel TDX
            </span>
          </div>

          {/* Headline */}
          <h1 className="mb-8 text-5xl font-bold tracking-tight md:text-6xl">
            Meeting intelligence{" "}
            <span className="italic text-muted-foreground">nobody else</span>{" "}
            can read.
          </h1>

          {/* Subhead */}
          <p className="mx-auto mb-10 max-w-2xl text-lg leading-relaxed text-muted-foreground md:text-xl">
            Invite the bot, get transcripts, signals, obligations, and a
            searchable memory of everything said — processed entirely inside
            an attested enclave. Not even we can see it.
          </p>

          {/* CTAs */}
          <div className="flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              href="/login"
              className="group flex transform items-center gap-2 rounded-full bg-foreground px-8 py-4 text-base font-medium text-background shadow-lg transition duration-300 hover:-translate-y-1 hover:shadow-xl"
            >
              Start for free
              <span
                className="transition-transform group-hover:translate-x-1"
                aria-hidden
              >
                →
              </span>
            </Link>
            <Link
              href={`/meeting/example-conclave-demo`}
              className="flex items-center gap-2 rounded-full border border-border bg-card px-8 py-4 text-base font-medium text-foreground/80 transition hover:border-input hover:bg-secondary"
            >
              See an example meeting
            </Link>
          </div>
        </div>

        {/* ── Dark closing slab ── */}
        <section className="mx-auto my-24 w-full max-w-5xl">
          <div className="relative overflow-hidden rounded-[3rem] bg-foreground px-6 py-20 text-center">
            <div
              className="absolute -top-24 left-1/2 h-72 w-[36rem] -translate-x-1/2 rounded-full bg-primary/25 blur-[100px]"
              aria-hidden
            />
            <div className="relative z-10">
              <h2 className="mb-4 text-3xl font-bold tracking-tight text-background md:text-4xl">
                Record everything. Reveal nothing.
              </h2>
              <p className="mx-auto mb-10 max-w-xl text-lg text-background/60">
                The operator provably can&apos;t read your meetings — remote
                attestation, not promises.
              </p>
              <Link
                href="/login"
                className="inline-flex items-center gap-2 rounded-full bg-card px-8 py-4 font-bold text-foreground shadow-lg transition hover:scale-105"
              >
                Get Conclave
              </Link>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
