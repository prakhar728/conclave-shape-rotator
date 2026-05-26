/* Style guide checkpoint — visit /style to review the Roman/arena design system. */
import { Laurel, SpqrSeal, ArchDivider } from "@/components/seal-marks";
import { AttestationWidget } from "@/components/attestation-widget";

const swatches: Array<{ name: string; varName: string; hex: string }> = [
  { name: "travertine",   varName: "--background",   hex: "#f0ead8" },
  { name: "stone",        varName: "--muted",        hex: "#e6dec9" },
  { name: "weathered",    varName: "--border",       hex: "#cabc99" },
  { name: "muted ink",    varName: "--muted-foreground", hex: "#6b5d49" },
  { name: "carved ink",   varName: "--foreground",   hex: "#2a2018" },
  { name: "porphyry",     varName: "--primary",      hex: "#5d2545" },
  { name: "arena ochre",  varName: "--gold",         hex: "#c08a3e" },
  { name: "blood",        varName: "--blood",        hex: "#8b2317" },
  { name: "basalt",       varName: "--basalt",       hex: "#1a1612" },
];

const forumStrip = [
  "TEE-VERIFIED",
  "INTEL TDX",
  "NIHIL EXPOSITUM",
  "SEALED VERDICTS",
  "ON-CHAIN ATTESTATION",
  "PHALA · BASE · SOLANA",
  "SPQR · CONCLAVIUM",
];

export default function StylePage() {
  return (
    <div className="min-h-screen arena-bg text-foreground">
      {/* ─── Header ─────────────────────────────────── */}
      <header className="border-b border-border">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Laurel className="h-7 w-7 text-primary" color="#5d2545" />
            <span className="font-display text-xl tracking-[0.18em] leading-none">
              CONCLAVE
            </span>
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              / style guide
            </span>
          </div>
          <nav className="flex items-center gap-6 text-sm font-serif">
            <a className="hover:text-primary" href="/">home</a>
            <a className="hover:text-primary" href="/setup">enter the lists</a>
            <a
              href="#"
              className="rounded-sm border border-foreground bg-foreground px-3 py-1.5 text-background hover:bg-primary hover:border-primary text-xs font-mono uppercase tracking-wider"
            >
              + convene a conclave
            </a>
          </nav>
        </div>
      </header>

      {/* ─── Hero ─────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <div className="grid lg:grid-cols-[1.15fr_1fr] gap-12 items-center">
          {/* Left: hero copy */}
          <div>
            <div className="bracket-label mb-4">CONFIDENTIAL · TEE-VERIFIED · NOVELTY EVAL</div>
            <h1 className="font-display text-5xl xl:text-6xl leading-[0.95] mb-6 tracking-tight whitespace-nowrap">
              <span className="block">SEALED VERDICTS.</span>
              <span className="block">BOUNDED SCORES.</span>
              <span className="block">ZERO EXPOSURE.</span>
            </h1>
            <p className="font-serif text-xl max-w-xl text-foreground/80 mb-8 leading-snug">
              Each idea enters the arena alone. The Conclave deliberates inside an
              Intel TDX enclave — your README, your idea, your code never leave
              your machine in plaintext. Only the verdict comes back, sealed.
            </p>
            <div className="flex items-center gap-3">
              <button className="rounded-sm border border-primary bg-primary px-5 py-2.5 text-primary-foreground hover:bg-primary/90 text-sm font-mono uppercase tracking-wider">
                + convene a conclave
              </button>
              <button className="rounded-sm border border-border bg-background px-5 py-2.5 text-foreground hover:border-foreground text-sm font-mono uppercase tracking-wider">
                read the codex
              </button>
            </div>
          </div>

          {/* Right: arena plate */}
          <figure className="relative">
            {/* Outer frame — thin border, gold inner rule */}
            <div className="border border-border p-2 bg-background">
              <div className="border border-[var(--gold)]/40 overflow-hidden relative">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/arena.jpg"
                  alt="An imagined Roman arena, banners flying, the lists assembled"
                  className="block w-full h-auto"
                  style={{
                    /* gentle warm wash so the image marries the cream background */
                    filter: "saturate(0.92) contrast(1.02)",
                  }}
                />
                {/* Soft vignette at edges to settle into the page */}
                <div
                  className="absolute inset-0 pointer-events-none"
                  style={{
                    background:
                      "linear-gradient(180deg, rgba(240,234,216,0.12) 0%, rgba(240,234,216,0) 18%, rgba(240,234,216,0) 82%, rgba(240,234,216,0.18) 100%)",
                  }}
                />
              </div>
            </div>
            {/* Caption strip */}
            <figcaption className="flex items-center justify-between mt-3 px-1">
              <span className="bracket-label">THE ARENA · IMAGINED</span>
              <span className="font-serif italic text-xs text-muted-foreground">
                where the lists are read aloud
              </span>
            </figcaption>
          </figure>
        </div>
      </section>

      <ArchDivider />

      {/* ─── Palette ─────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-16">
        <div className="bracket-label mb-3">I · THE PALETTE</div>
        <h2 className="font-display text-4xl mb-2 tracking-wide">FRESCO ON STONE</h2>
        <p className="font-serif italic text-muted-foreground mb-8">
          Travertine cream, porphyry purple, arena ochre. Borders only — no shadows.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-3 gap-4">
          {swatches.map((s) => (
            <div key={s.name} className="paper-card p-4">
              <div
                className="h-20 rounded-sm border border-border mb-3"
                style={{ background: s.hex }}
              />
              <div className="text-sm font-display tracking-wide uppercase">{s.name}</div>
              <div className="text-xs text-muted-foreground font-mono">{s.hex}</div>
              <div className="text-[10px] text-muted-foreground mt-1 font-mono">{s.varName}</div>
            </div>
          ))}
        </div>
      </section>

      <ArchDivider />

      {/* ─── Type scale ─────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-16">
        <div className="bracket-label mb-3">II · TYPOGRAPHY</div>
        <h2 className="font-display text-4xl mb-2 tracking-wide">THREE VOICES</h2>
        <p className="font-serif italic text-muted-foreground mb-8">
          Cinzel speaks for the Empire. Garamond for the historian. Plex Mono for the cipher.
        </p>
        <div className="paper-card p-8 space-y-8">
          <div>
            <div className="bracket-label mb-2">DISPLAY · CINZEL · 7XL</div>
            <div className="font-display text-7xl leading-none tracking-tight">THE ARENA</div>
          </div>
          <div>
            <div className="bracket-label mb-2">DISPLAY · CINZEL · 4XL</div>
            <div className="font-display text-4xl leading-none tracking-wide">SEALED VERDICTS</div>
          </div>
          <hr className="border-border" />
          <div>
            <div className="bracket-label mb-2">BODY · GARAMOND · LG</div>
            <p className="font-serif text-lg leading-snug">
              Each submission enters the lists alone. The Conclave evaluates it inside
              an Intel TDX enclave — raw README content, idea text, and code summaries
              are encrypted in transit, processed in memory, and discarded after scoring.
              Only bounded scores leave the chamber.
            </p>
          </div>
          <div>
            <div className="bracket-label mb-2">BODY · GARAMOND · ITALIC</div>
            <p className="font-serif italic text-lg text-muted-foreground leading-snug">
              The crowd sees the verdict. The deliberation stays in the chamber.
            </p>
          </div>
          <div>
            <div className="bracket-label mb-2">CIPHER · PLEX MONO · XS</div>
            <pre className="font-mono text-xs bg-muted p-3 rounded-sm border border-border overflow-x-auto leading-relaxed">{`POST /instances/{id}/submit
  └─ encrypt-to-enclave({ idea_summary, readme_digest, track })
  └─ enclave.score()  →  { novelty: 0.84, faction: 3, alignment: 0.91 }
  └─ publish_attestation(quote_hex)
       0xa1b2c3d4e5f6...7890abcd`}</pre>
          </div>
        </div>
      </section>

      <ArchDivider />

      {/* ─── Components ─────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-16">
        <div className="bracket-label mb-3">III · INSTRUMENTS</div>
        <h2 className="font-display text-4xl mb-8 tracking-wide">CARDS · BUTTONS · BADGES</h2>

        {/* Stat cards */}
        <div className="grid md:grid-cols-3 gap-4 mb-10">
          <div className="paper-card p-5">
            <div className="bracket-label mb-3">COHORT SIZE</div>
            <div className="font-display text-5xl leading-none">21</div>
            <div className="gold-rule mt-2 mb-2 w-12" />
            <div className="font-serif text-sm text-muted-foreground">gladiators in the lists</div>
          </div>
          <div className="paper-card p-5">
            <div className="bracket-label mb-3">LAST DELIBERATION</div>
            <div className="font-display text-5xl leading-none">04:21</div>
            <div className="gold-rule mt-2 mb-2 w-12" />
            <div className="font-serif text-sm text-muted-foreground">UTC · 2026-05-09</div>
          </div>
          <div className="paper-card p-5">
            <div className="bracket-label mb-3">NAME COLLISIONS</div>
            <div className="font-display text-5xl leading-none">00</div>
            <div className="gold-rule mt-2 mb-2 w-12" />
            <div className="font-serif text-sm text-muted-foreground">pairs flagged</div>
          </div>
        </div>

        {/* Buttons */}
        <div className="flex flex-wrap items-center gap-3 mb-10">
          <button className="rounded-sm border border-primary bg-primary px-4 py-2 text-primary-foreground hover:bg-primary/90 text-xs font-mono uppercase tracking-wider">
            primary · convene
          </button>
          <button className="rounded-sm border border-foreground bg-foreground px-4 py-2 text-background hover:bg-primary hover:border-primary text-xs font-mono uppercase tracking-wider">
            ink · trigger eval
          </button>
          <button className="rounded-sm border border-border bg-background px-4 py-2 text-foreground hover:border-foreground text-xs font-mono uppercase tracking-wider">
            outline · refresh
          </button>
          <button
            className="rounded-sm border border-blood bg-background px-4 py-2 text-blood hover:bg-blood hover:text-background text-xs font-mono uppercase tracking-wider"
            style={{ borderColor: "#8b2317", color: "#8b2317" }}
          >
            blood · destroy
          </button>
          <button className="rounded-sm border border-border bg-muted px-4 py-2 text-muted-foreground text-xs font-mono uppercase tracking-wider" disabled>
            disabled
          </button>
        </div>

        {/* Badges */}
        <div className="flex flex-wrap items-center gap-2 mb-10">
          <span className="mono-badge">faction #3</span>
          <span className="mono-badge" style={{ background: "#5d2545", color: "#f0ead8" }}>verdict sealed</span>
          <span className="mono-badge" style={{ background: "#c08a3e", color: "#2a2018" }}>imperial gold</span>
          <span className="mono-badge" style={{ background: "#4a6a3a", color: "#f0ead8" }}>victorious</span>
          <span className="mono-badge" style={{ background: "#8b2317", color: "#f0ead8" }}>defeated</span>
        </div>

        {/* Inscribed plaque (form surface) */}
        <div className="plaque p-6">
          <div className="bracket-label mb-3">INSCRIBED PLAQUE · /SETUP SURFACE</div>
          <label className="block text-sm font-serif mb-1">hackathon name</label>
          <input
            className="w-full rounded-sm border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:border-primary"
            placeholder="e.g. Solana Frontier 2026"
            defaultValue="Solana Frontier 2026"
          />
          <label className="block text-sm font-serif mt-4 mb-1">end date</label>
          <input
            type="date"
            className="rounded-sm border border-border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:border-primary"
            defaultValue="2026-06-15"
          />
        </div>
      </section>

      <ArchDivider />

      {/* ─── Basalt slab — How the arena works ─── */}
      <section className="basalt-slab py-24 mt-8">
        <div className="mx-auto max-w-6xl px-6">
          <div className="bracket-label mb-3" style={{ color: "#8a7a64" }}>
            IV · MECHANICS OF THE GAMES
          </div>
          <h2 className="font-display text-5xl mb-12 tracking-wide" style={{ color: "var(--basalt-foreground)" }}>
            THREE ACTS, ONE SEAL.
          </h2>
          <div className="grid md:grid-cols-3 gap-6">
            {[
              { n: "I",   t: "Local rites", d: "Your idea, README, and code are summarized on your machine. The raw text never leaves." },
              { n: "II",  t: "Sealed deliberation", d: "The digest is encrypted to the enclave's attested key. The Conclave reads it inside TDX, judges, and forgets." },
              { n: "III", t: "Bounded verdict", d: "You receive novelty, alignment, and faction id. The operator sees aggregate. Nobody sees the deliberation." },
            ].map((p) => (
              <div
                key={p.n}
                className="rounded-sm border p-6"
                style={{ borderColor: "var(--basalt-border)", background: "#0f0c09" }}
              >
                <div className="font-display text-3xl mb-3" style={{ color: "#c08a3e" }}>{p.n}</div>
                <div
                  className="font-display text-lg uppercase tracking-wider mb-2"
                  style={{ color: "var(--basalt-foreground)" }}
                >
                  {p.t}
                </div>
                <div className="font-serif text-base" style={{ color: "#a99c87" }}>
                  {p.d}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── The Imperial Seal — attestation states ─── */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <div className="bracket-label mb-3">V · THE IMPERIAL SEAL</div>
        <h2 className="font-display text-4xl mb-2 tracking-wide">PROOF WITHOUT EXPOSURE</h2>
        <p className="font-serif italic text-muted-foreground mb-8">
          The deliberation is private. The seal is public. Anyone can verify
          that the Conclave convened — nobody can recover what was said.
        </p>
        <div className="grid md:grid-cols-3 gap-4">
          {/* Idle */}
          <div className="paper-card p-6">
            <div className="bracket-label mb-3">UNSEALED</div>
            <div className="flex items-center gap-4">
              <div className="h-20 w-20 rounded-full border-2 border-dashed border-border flex items-center justify-center text-2xl text-muted-foreground">
                ◯
              </div>
              <div>
                <div className="font-display text-base uppercase tracking-wider">awaiting</div>
                <div className="font-serif text-sm text-muted-foreground italic">no quote published</div>
              </div>
            </div>
          </div>
          {/* Verifying */}
          <div className="paper-card p-6">
            <div className="bracket-label mb-3">VERIFYING</div>
            <div className="flex items-center gap-4">
              <div className="h-20 w-20 rounded-full border-2 border-primary flex items-center justify-center text-2xl text-primary animate-pulse">
                <Laurel className="h-12 w-12" color="#5d2545" />
              </div>
              <div>
                <div className="font-display text-base uppercase tracking-wider">checking</div>
                <div className="font-serif text-sm text-muted-foreground italic">tdx quote in flight…</div>
              </div>
            </div>
          </div>
          {/* Verified */}
          <div className="paper-card p-6 border-primary">
            <div className="bracket-label mb-3">SEALED</div>
            <div className="flex items-center gap-4">
              <div className="seal-stamp">
                <SpqrSeal className="h-20 w-20" />
              </div>
              <div>
                <div className="font-display text-base uppercase tracking-wider">imperial seal</div>
                <div className="font-mono text-[10px] text-muted-foreground break-all">
                  0xa1b2c3d4e5f6…7890abcd
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Live AttestationWidget preview ─── */}
      <section className="mx-auto max-w-3xl px-6 pb-20">
        <div className="bracket-label mb-3">VI · LIVE ATTESTATION WIDGET</div>
        <h2 className="font-display text-3xl mb-2 tracking-wide">THE SEAL IN CONTEXT</h2>
        <p className="font-serif italic text-muted-foreground mb-6">
          The actual component as it will appear on /setup and elsewhere.
        </p>
        <AttestationWidget />
      </section>

      {/* ─── Forum announcements marquee ─── */}
      <div className="border-y border-border bg-muted py-3 marquee">
        <div className="marquee-track text-xs uppercase tracking-[0.18em] text-muted-foreground font-mono">
          {[...forumStrip, ...forumStrip].map((it, i) => (
            <span key={i} className="inline-flex items-center gap-3">
              <span>{it}</span>
              <span aria-hidden style={{ color: "var(--gold)" }}>✦</span>
            </span>
          ))}
        </div>
      </div>

      {/* ─── Footer ─── */}
      <footer className="mx-auto max-w-6xl px-6 py-10 flex flex-col md:flex-row md:justify-between gap-4">
        <div className="flex items-center gap-3">
          <Laurel className="h-5 w-5" color="#6b5d49" />
          <span className="font-mono text-xs text-muted-foreground uppercase tracking-wider">
            CONCLAVE · style guide checkpoint · 2026-05-09
          </span>
        </div>
        <div className="font-serif italic text-xs text-muted-foreground">
          built on phala · base · solana
        </div>
      </footer>
    </div>
  );
}
