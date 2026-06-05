/**
 * Signed-in app chrome — Vantage language (user-supplied reference,
 * 2026-06-04): stone-50 sidebar with a workspace profile chip, white
 * bordered+shadowed active nav item with orange icon, uppercase section
 * labels, orange pill CTA, and the attested badge + sign-out pinned to
 * the bottom. No topbar — pages own their headers (see PageHeader).
 *
 * Layout contract: the content column is `flex min-h-screen flex-col`;
 * full-bleed pages (graph) claim leftover viewport with `flex-1`, normal
 * pages render a <main> that scrolls with the body.
 *
 * Logout hits POST /api/auth/v1/logout which revokes server-side and
 * clears the cookie — the next protected-route hit gets bounced by
 * middleware.ts to /login.
 */
"use client";

import {
  Check,
  ChevronsUpDown,
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
import { useEffect, useRef, useState } from "react";

import { AttestedBadge } from "@/components/attested-badge";
import { cn } from "@/lib/utils";
import { SearchBox } from "@/components/search-box";
import { useWorkspace } from "@/components/workspace-provider";
import { auth, type User } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { href: "/search", label: "Search", icon: Search },
  { href: "/entities", label: "Entities", icon: Tags },
  { href: "/obligations", label: "Obligations", icon: ListChecks },
  { href: "/graph", label: "Graph", icon: Share2 },
] as const;

export function AppShell({
  user,
  children,
}: {
  user: User;
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
      {/* ── Sidebar (Vantage mockup) ── */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar p-4 md:flex">
        <WorkspaceSwitcher />

        <nav className="space-y-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-2 text-xs transition",
                  active
                    ? "border border-border bg-card font-medium text-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-secondary",
                )}
              >
                <Icon
                  className={cn("size-3.5", active && "text-primary")}
                  aria-hidden
                />
                {label}
              </Link>
            );
          })}
        </nav>

        <Link
          href="/invite"
          className="mt-6 flex items-center justify-center gap-2 rounded-full bg-primary px-3 py-2.5 text-xs font-bold text-primary-foreground shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 active:scale-95"
        >
          <Plus className="size-3.5" aria-hidden />
          Invite bot
        </Link>

        <div className="mt-auto space-y-3 border-t border-border pt-4">
          <div className="px-2">
            <AttestedBadge />
          </div>
          <p className="truncate px-2 text-[11px] text-muted-foreground">
            {user.email}
          </p>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          >
            <LogOut className="size-3.5" aria-hidden />
            Sign out
          </button>
        </div>
      </aside>

      {/* ── Content column ── */}
      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        {/* Mobile-only slim bar (sidebar is hidden <md). */}
        <header className="flex items-center justify-between border-b border-border bg-card px-4 py-3 md:hidden">
          <Link href="/dashboard" className="flex items-center gap-2">
            <span className="flex size-7 items-center justify-center rounded-full bg-foreground font-serif text-sm text-background">
              C
            </span>
            <span className="text-sm font-bold tracking-tight">Conclave</span>
          </Link>
          <div className="flex items-center gap-3">
            <AttestedBadge />
            <button
              onClick={handleLogout}
              className="text-xs text-muted-foreground"
            >
              Sign out
            </button>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}

/**
 * Sidebar workspace chip → dropdown: list with checkmark on current,
 * "+ New workspace" prompts for a name and creates+selects it.
 */
function WorkspaceSwitcher() {
  const { workspaces, workspace, selectWorkspace, createWorkspace } =
    useWorkspace();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  async function handleCreate() {
    const name = window.prompt("Name for the new workspace:")?.trim();
    if (!name) return;
    setBusy(true);
    try {
      await createWorkspace(name);
      setOpen(false);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to create workspace");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div ref={boxRef} className="relative mb-8">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 rounded-lg p-2 text-left transition hover:bg-secondary"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-card bg-foreground font-serif text-sm text-background shadow-sm">
          C
        </span>
        <span className="min-w-0 flex-1 truncate text-xs font-bold">
          {workspace?.name ?? (workspaces === null ? "…" : "Conclave")}
        </span>
        <ChevronsUpDown
          className="size-3.5 shrink-0 text-muted-foreground"
          aria-hidden
        />
      </button>

      {open ? (
        <div
          role="listbox"
          className="absolute left-0 right-0 top-full z-50 mt-1 overflow-hidden rounded-xl border border-border bg-card p-1 shadow-xl"
        >
          {(workspaces ?? []).map((w) => (
            <button
              key={w.id}
              role="option"
              aria-selected={w.id === workspace?.id}
              onClick={() => {
                selectWorkspace(w.id);
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs font-medium transition hover:bg-secondary"
            >
              <span className="min-w-0 flex-1 truncate">{w.name}</span>
              {w.id === workspace?.id ? (
                <Check className="size-3.5 shrink-0 text-primary" aria-hidden />
              ) : null}
            </button>
          ))}
          <button
            onClick={handleCreate}
            disabled={busy}
            className="flex w-full items-center gap-2 rounded-lg border-t border-border px-2 py-2 text-left text-xs font-medium text-muted-foreground transition hover:bg-secondary hover:text-foreground disabled:opacity-50"
          >
            <Plus className="size-3.5" aria-hidden />
            {busy ? "Creating…" : "New workspace"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Vantage-style page header: serif headline + optional subtext, with
 * round icon-button actions on the right (global search lives here now
 * that there's no topbar).
 */
export function PageHeader({
  title,
  subtitle,
  workspaceId,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  workspaceId?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-serif text-3xl leading-tight md:text-4xl">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        {workspaceId ? <SearchBox workspaceId={workspaceId} /> : null}
        {actions}
      </div>
    </div>
  );
}
