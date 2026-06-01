/**
 * Placeholder landing page.
 *
 * Real signup/login lands in 1.10 and the dashboard in 1.12 — for now
 * this just confirms the scaffold + tailwind + dark mode + rewrites are
 * wired correctly, and establishes the Proton-style aesthetic baseline
 * (BUILD_DOC §4 visual direction decision).
 */
export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-black text-zinc-100 font-sans">
      <main className="flex w-full max-w-xl flex-col gap-6 px-8">
        <p className="text-xs uppercase tracking-[0.3em] text-zinc-500">
          Conclave
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">
          A privacy-preserving knowledge layer
          <br />
          for your team&apos;s conversations.
        </h1>
        <p className="max-w-md text-zinc-400">
          Invite the bot. Get a confidential transcript and signals.
          Never lose what was said.
        </p>
        <p className="text-xs text-zinc-600">
          Frontend scaffold — Phase 1.8. Signup, dashboard, and the rest
          land in 1.10+.
        </p>
      </main>
    </div>
  );
}
