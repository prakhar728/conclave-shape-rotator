/**
 * Public landing page. Marketing surface is intentionally thin in v1 —
 * a one-liner, the wordmark, and a sign-in CTA. v1.5 takes the launch-
 * page treatment.
 */
import Link from "next/link";

import { AttestedBadge } from "@/components/attested-badge";
import { Wordmark } from "@/components/wordmark";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-vault-atmosphere px-6">
      <main className="flex w-full max-w-xl flex-col gap-8">
        <div className="flex items-baseline gap-3">
          <Wordmark size="lg" />
          <AttestedBadge />
        </div>
        <h1 className="font-serif text-6xl leading-[1.05]">
          A privacy-preserving knowledge layer for your team&apos;s
          conversations.
        </h1>
        <p className="max-w-md text-muted-foreground">
          Invite the bot. Get a confidential transcript and signals.
          Never lose what was said —{" "}
          <span className="italic">
            and never let anyone else read it.
          </span>
        </p>
        <div>
          <Link
            href="/login"
            className="inline-flex h-9 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80"
          >
            Sign in
          </Link>
        </div>
      </main>
    </div>
  );
}
