/**
 * Public landing page. Marketing surface is intentionally thin in v1 —
 * a one-liner, the wordmark, and a sign-in CTA. v1.5 takes the launch-
 * page treatment.
 */
import Link from "next/link";

import { Wordmark } from "@/components/wordmark";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-6">
      <main className="flex w-full max-w-xl flex-col gap-8">
        <Wordmark size="lg" />
        <h1 className="text-4xl font-semibold tracking-tight">
          A privacy-preserving knowledge layer
          <br />
          for your team&apos;s conversations.
        </h1>
        <p className="max-w-md text-muted-foreground">
          Invite the bot. Get a confidential transcript and signals.
          Never lose what was said.
        </p>
        <div>
          <Link
            href="/login"
            className="inline-flex h-8 items-center rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80"
          >
            Sign in
          </Link>
        </div>
      </main>
    </div>
  );
}
