/**
 * Conclave wordmark — Vantage language: dark circle with a serif initial
 * + bold name. (Vantage uses a white circle on dark nav; we invert on
 * light surfaces and flip via the `inverted` prop on dark ones.)
 */
import Link from "next/link";

import { cn } from "@/lib/utils";

export function Wordmark({
  size = "default",
  href = "/",
  className,
  inverted = false,
}: {
  size?: "default" | "lg";
  href?: string | null;
  className?: string;
  /** For dark surfaces (landing pill nav): white circle, dark glyph. */
  inverted?: boolean;
}) {
  const inner = (
    <span className={cn("flex items-center gap-2.5", className)}>
      <span
        className={cn(
          "flex items-center justify-center rounded-full font-bold shadow-sm",
          inverted
            ? "bg-background text-foreground"
            : "bg-foreground text-background",
          size === "lg" ? "size-10 text-2xl" : "size-8 text-lg",
        )}
      >
        C
      </span>
      <span
        className={cn(
          "font-bold tracking-tight",
          inverted ? "text-background" : "text-foreground",
          size === "lg" ? "text-xl" : "text-base",
        )}
      >
        Conclave
      </span>
    </span>
  );

  if (href === null) return inner;
  return (
    <Link href={href} className="inline-block">
      {inner}
    </Link>
  );
}
