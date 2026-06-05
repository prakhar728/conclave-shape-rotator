/**
 * Conclave wordmark.
 *
 * Bold Jakarta with an emerald terminal period: the full stop as the
 * mark — sealed, nothing leaves.
 *
 * `size="lg"` is for the landing/login page; default works for the shell.
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
        "font-bold tracking-tight",
        size === "lg" ? "text-2xl" : "text-lg",
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
