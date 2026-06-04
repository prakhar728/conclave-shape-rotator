/**
 * Shared header for signed-in pages.
 *
 * Wordmark refinement is 1.15's job; this is the Geist-typeset baseline.
 * Logout button hits POST /api/auth/v1/logout which revokes server-side
 * and clears the cookie — the next protected-route hit gets bounced by
 * middleware.ts to /login.
 */
"use client";

import { useRouter } from "next/navigation";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { SearchBox } from "@/components/search-box";
import { Wordmark } from "@/components/wordmark";
import { auth, type User, type Workspace } from "@/lib/api";

export function AppHeader({
  user,
  workspace,
}: {
  user: User;
  workspace: Workspace | null;
}) {
  const router = useRouter();

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
      </div>
      <div className="flex items-center gap-4">
        {workspace ? <SearchBox workspaceId={workspace.id} /> : null}
        <Link
          href="/entities"
          className="hidden text-xs text-muted-foreground hover:text-foreground sm:inline"
        >
          Entities
        </Link>
        <Link
          href="/obligations"
          className="hidden text-xs text-muted-foreground hover:text-foreground sm:inline"
        >
          Obligations
        </Link>
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
