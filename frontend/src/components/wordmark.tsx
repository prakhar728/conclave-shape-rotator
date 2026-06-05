/**
 * Conclave wordmark — Editorial Vault.
 *
 * Typeset in Instrument Serif (--font-heading) with an emerald terminal
 * period: the full stop as the mark — sealed, nothing leaves. Classic
 * dossier gravitas against the utilitarian Geist body.
 *
 * `size="lg"` is for the landing/login page; default works for the header.
 */
import Link from "next/link";

import { cn } from "@/lib/utils";

export function Wordmark({
  size = "default",
  href = "/",
  className,
}: {
  size?: "default" | "lg";
  href?: string | null;
  className?: string;
}) {
  const inner = (
    <span
      className={cn(
        "font-heading tracking-tight",
        size === "lg" ? "text-3xl" : "text-xl",
        className,
      )}
    >
      Conclave<span className="text-primary">.</span>
    </span>
  );

  if (href === null) return inner;
  return (
    <Link href={href} className="inline-block">
      {inner}
    </Link>
  );
}
