/**
 * Signed-in app chrome (full-pivot 2026-06-04): persistent left sidebar
 * (wordmark, icon nav, sign-out) + topbar (workspace, attested badge,
 * search, user) around a scrolling content column. Replaces the old
 * header-only AppHeader.
 *
 * Layout contract: the content column is `flex min-h-screen flex-col`,
 * so full-bleed pages (graph) can claim leftover viewport with `flex-1`
 * while normal pages just render a <main> that scrolls with the body.
 *
 * Logout hits POST /api/auth/v1/logout which revokes server-side and
 * clears the cookie — the next protected-route hit gets bounced by
 * middleware.ts to /login.
 */
"use client";

import {
  LayoutGrid,
  ListChecks,
  LogOut,
  Plus,
  Search,
  Share2,
  Tags,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { AttestedBadge } from "@/components/attested-badge";
import { cn } from "@/lib/utils";
import { SearchBox } from "@/components/search-box";
import { Wordmark } from "@/components/wordmark";
import { auth, type User, type Workspace } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { href: "/search", label: "Search", icon: Search },
  { href: "/entities", label: "Entities", icon: Tags },
  { href: "/obligations", label: "Obligations", icon: ListChecks },
  { href: "/graph", label: "Graph", icon: Share2 },
] as const;

export function AppShell({
  user,
  workspace,
  children,
}: {
  user: User;
  workspace: Workspace | null;
  children: React.ReactNode;
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
    <div className="flex min-h-screen bg-background">
      {/* ── Sidebar ── */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-4 py-6 md:flex">
        <div className="px-3">
          <Wordmark href="/dashboard" />
        </div>

        <p className="mt-8 mb-2 px-3 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Overview
        </p>
        <nav className="flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>

        <Link
          href="/invite"
          className="mt-6 flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/85"
        >
          <Plus className="size-4" aria-hidden />
          Invite bot
        </Link>

        <div className="mt-auto border-t border-sidebar-border pt-4">
          <p className="truncate px-3 text-xs text-muted-foreground">
            {user.email}
          </p>
          <button
            onClick={handleLogout}
            className="mt-2 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <LogOut className="size-4" aria-hidden />
            Sign out
          </button>
        </div>
      </aside>

      {/* ── Content column ── */}
      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-border bg-card px-6 py-3">
          <div className="flex min-w-0 items-center gap-3">
            {/* Mobile: no sidebar, so the wordmark lives here. */}
            <span className="md:hidden">
              <Wordmark href="/dashboard" />
            </span>
            {workspace ? (
              <span className="hidden truncate text-sm font-medium md:inline">
                {workspace.name}
              </span>
            ) : null}
            <AttestedBadge />
          </div>
          <div className="flex items-center gap-3">
            {workspace ? <SearchBox workspaceId={workspace.id} /> : null}
            {/* Mobile escape hatches for the hidden sidebar. */}
            <Link
              href="/obligations"
              className="text-xs text-muted-foreground hover:text-foreground md:hidden"
            >
              Board
            </Link>
            <button
              onClick={handleLogout}
              className="text-xs text-muted-foreground hover:text-foreground md:hidden"
            >
              Sign out
            </button>
            <span
              className="hidden size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold uppercase text-secondary-foreground md:flex"
              title={user.email}
            >
              {user.email.slice(0, 2)}
            </span>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
