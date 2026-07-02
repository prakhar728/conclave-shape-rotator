/**
 * Conclave wordmark — the waveform logo mark + bold name. The logo is a
 * self-contained sharp mark (white frame) that reads on light or dark; the
 * `inverted` prop only flips the wordmark text color for dark surfaces.
 */
import Image from "next/image";
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
      <Image
        src="/logo.png"
        alt="Conclave logo"
        width={40}
        height={40}
        priority
        className={cn(
          "rounded-none object-contain",
          size === "lg" ? "size-10" : "size-8",
        )}
      />
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
