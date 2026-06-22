import Link from "next/link";

/**
 * Owner-only entry point from the meeting view into the refinement editor.
 * Matches the brutalist CTA style used elsewhere on the meeting page.
 */
export function RefineLink({ sessionId }: { sessionId: string }) {
  return (
    <Link
      href={`/meeting/${sessionId}/refine`}
      data-testid="refine-link"
      className="inline-flex items-center gap-2 rounded-none border border-foreground bg-foreground px-4 py-2 text-xs font-bold uppercase tracking-widest text-background transition-colors hover:bg-background hover:text-foreground"
    >
      Review &amp; refine transcript &rarr;
    </Link>
  );
}
