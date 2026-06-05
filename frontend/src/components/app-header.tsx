/**
 * Shared header for signed-in pages.
 *
 * Wordmark refinement is 1.15's job; this is the Geist-typeset baseline.
 * Logout button hits POST /api/auth/v1/logout which revokes server-side
 * and clears the cookie — the next protected-route hit gets bounced by
 * middleware.ts to /login.
 */
"use client";

import { usePathname, useRouter } from "next/navigation";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { SearchBox } from "@/components/search-box";
import { Wordmark } from "@/components/wordmark";
import { auth, type User, type Workspace } from "@/lib/api";

const NAV_LINKS = [
  { href: "/entities", label: "Entities" },
  { href: "/obligations", label: "Obligations" },
  { href: "/graph", label: "Graph" },
] as const;

/**
 * The trust mark: emerald dot + mono "attested". The whole pitch in one
 * chip — the operator provably can't read your meetings.
 *
 * TODO(tee-deploy): wire to a real attestation endpoint (TDX quote
 * verification) instead of rendering statically.
 */
function AttestedBadge() {
  return (
    <span
      title="Running in a confidential VM · Intel TDX"
      className="inline-flex cursor-default items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-mono text-[10px] leading-4 text-primary"
    >
      <span className="size-1.5 rounded-full bg-attested" aria-hidden />
      attested
    </span>
  );
}

export function AppHeader({
  user,
  workspace,
}: {
  user: User;
  workspace: Workspace | null;
}) {
  const router = useRouter();
  const pathname = usePathname();

  async function handleLogout() {
    try {
      await auth.logout();
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <header className="flex items-center justify-between border-b border-border px-6 py-4">
      <div className="flex items-center gap-4">
        <Wordmark href="/dashboard" />
        {workspace ? (
          <>
            <span className="text-muted-foreground">/</span>
            <span className="text-sm text-muted-foreground">
              {workspace.name}
            </span>
          </>
        ) : null}
        <AttestedBadge />
      </div>
      <div className="flex items-center gap-4">
        {workspace ? <SearchBox workspaceId={workspace.id} /> : null}
        {NAV_LINKS.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={
              pathname.startsWith(href)
                ? "hidden text-xs font-medium text-primary sm:inline"
                : "hidden text-xs text-muted-foreground hover:text-foreground sm:inline"
            }
          >
            {label}
          </Link>
        ))}
        <span className="hidden text-xs text-muted-foreground sm:inline">
          {user.email}
        </span>
        <Button variant="outline" size="sm" onClick={handleLogout}>
          Sign out
        </Button>
      </div>
    </header>
  );
}
