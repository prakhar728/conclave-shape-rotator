/**
 * Conclave wordmark.
 *
 * v1: typeset wordmark using Geist (set as --font-sans in layout.tsx).
 * Uppercase, modest letter-spacing — utilitarian, privacy-tech aesthetic
 * per BUILD_DOC §4. Real logo design is deferred to v1.5.
 *
 * `size="lg"` is for the landing page; default works for the header.
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
        "font-semibold tracking-[0.22em] uppercase",
        size === "lg" ? "text-base" : "text-sm",
        className,
      )}
    >
      Conclave
    </span>
  );

  if (href === null) return inner;
  return (
    <Link href={href} className="inline-block">
      {inner}
    </Link>
  );
}
