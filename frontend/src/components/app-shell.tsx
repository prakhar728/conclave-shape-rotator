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
  Calendar,
  Check,
  ChevronsUpDown,
  Inbox,
  LayoutGrid,
  ListChecks,
  LogOut,
  MessageSquare,
  Plus,
  Search,
  Settings,
  Share2,
  Tags,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { fmt, useRecording } from "@/components/recording-provider";
import { SearchBox } from "@/components/search-box";
import { useWorkspace } from "@/components/workspace-provider";
import { auth, type User } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutGrid },
  { href: "/calendar", label: "Calendar", icon: Calendar },
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
      {/* ── Sidebar (Brutalist style) ── */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-sidebar p-4 md:flex">
        <WorkspaceSwitcher />

        <RecordingIndicator />

        <nav className="space-y-1.5">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 px-3 py-2 text-xs font-bold uppercase tracking-wider transition-all",
                  active
                    ? "border border-foreground bg-primary text-primary-foreground font-black shadow-sm"
                    : "text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent",
                )}
              >
                <Icon
                  className="size-3.5"
                  aria-hidden
                />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-6 flex items-center gap-2">
          <Link
            href="/invite"
            className="flex flex-1 items-center justify-center gap-2 rounded-none border border-foreground bg-primary px-3 py-2.5 text-xs font-bold uppercase tracking-widest text-primary-foreground transition-all hover:bg-muted-foreground active:scale-98"
          >
            <Plus className="size-3.5" aria-hidden />
            Invite bot
          </Link>
          <Link
            href="/calendar"
            title="Calendar"
            aria-label="Calendar"
            className={cn(
              "flex size-9 shrink-0 items-center justify-center rounded-none border border-border bg-card shadow-sm transition hover:bg-secondary",
              pathname.startsWith("/calendar")
                ? "text-primary border-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Calendar className="size-4" aria-hidden />
          </Link>
        </div>

        <div className="mt-auto space-y-3 border-t border-border pt-4">
          <Link
            href={`/feedback?from=${encodeURIComponent(pathname)}`}
            className={cn(
              "flex items-center gap-2.5 px-3 py-2 text-xs font-bold uppercase tracking-wider transition-all",
              pathname.startsWith("/feedback")
                ? "border border-foreground bg-primary text-primary-foreground font-black shadow-sm"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent",
            )}
          >
            <MessageSquare className="size-3.5" aria-hidden />
            Feedback
          </Link>
          {user.is_admin ? (
            <Link
              href="/admin/feedback"
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 text-xs font-bold uppercase tracking-wider transition-all",
                pathname.startsWith("/admin/feedback")
                  ? "border border-foreground bg-primary text-primary-foreground font-black shadow-sm"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent",
              )}
            >
              <Inbox className="size-3.5" aria-hidden />
              Feedback inbox
            </Link>
          ) : null}
          <Link
            href="/settings"
            className={cn(
              "flex items-center gap-2.5 px-3 py-2 text-xs font-bold uppercase tracking-wider transition-all",
              pathname.startsWith("/settings")
                ? "border border-foreground bg-primary text-primary-foreground font-black shadow-sm"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent",
            )}
          >
            <Settings
              className="size-3.5"
              aria-hidden
            />
            Settings
          </Link>
          <p className="truncate px-3 text-[10px] font-mono tracking-tight text-muted-foreground">
            {user.email}
          </p>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-xs font-bold uppercase tracking-wider text-muted-foreground hover:bg-secondary hover:text-foreground border border-transparent transition-all"
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
            <span className="flex size-7 items-center justify-center rounded-none border border-foreground bg-foreground text-sm font-black text-background">
              C
            </span>
            <span className="text-sm font-bold tracking-tight">Conclave</span>
          </Link>
          <div className="flex items-center gap-3">
            <RecordingIndicator compact />
            <button
              onClick={handleLogout}
              className="text-xs font-bold tracking-wider uppercase text-muted-foreground"
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
 * "Still recording" indicator (Task #14). The recording session lives in the
 * global `RecordingProvider`, so it survives navigation — this links back to the
 * live page from anywhere. Hidden when idle, on a finished/errored session, or
 * while already viewing that recording's own page.
 */
function RecordingIndicator({ compact = false }: { compact?: boolean }) {
  const { recording } = useRecording();
  const pathname = usePathname();
  if (!recording) return null;
  const isLive =
    recording.status === "starting" ||
    recording.status === "recording" ||
    recording.status === "ending";
  if (!isLive) return null;
  if (pathname === `/recording/${recording.id}`) return null;

  const ending = recording.status === "ending";
  if (compact) {
    return (
      <Link
        href={`/recording/${recording.id}`}
        aria-label="Return to live recording"
        className="inline-flex items-center gap-1.5 rounded-full border border-destructive bg-destructive/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-destructive"
      >
        <span className="size-2 animate-pulse rounded-full bg-destructive" />
        {ending ? "Ending" : fmt(recording.seconds)}
      </Link>
    );
  }
  return (
    <Link
      href={`/recording/${recording.id}`}
      className="mb-4 flex items-center gap-2.5 rounded-none border border-destructive bg-destructive/10 px-3 py-2 text-xs font-bold uppercase tracking-wider text-destructive transition hover:bg-destructive/20"
    >
      <span className="size-2.5 shrink-0 animate-pulse rounded-full bg-destructive" />
      <span className="min-w-0 flex-1 truncate">
        {ending ? "Ending meeting…" : `Recording · ${fmt(recording.seconds)}`}
      </span>
    </Link>
  );
}

/**
 * Sidebar workspace switcher: simple dropdown menu with brutalist border style.
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
        className="flex w-full items-center gap-3 rounded-none border border-border bg-card p-2.5 text-left transition hover:bg-secondary hover:border-foreground"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-none border border-foreground bg-foreground text-sm font-black text-background shadow-sm">
          C
        </span>
        <span className="min-w-0 flex-1 truncate text-xs font-black uppercase tracking-wider">
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
          className="absolute left-0 right-0 top-full z-50 mt-1.5 overflow-hidden rounded-none border border-foreground bg-card p-1 shadow-md"
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
              className="flex w-full items-center gap-2 rounded-none px-2 py-2 text-left text-xs font-semibold uppercase tracking-wider transition hover:bg-secondary"
            >
              <span className="min-w-0 flex-1 truncate">{w.name}</span>
              {w.id === workspace?.id ? (
                <Check className="size-3.5 shrink-0 text-foreground" aria-hidden />
              ) : null}
            </button>
          ))}
          <button
            onClick={handleCreate}
            disabled={busy}
            className="flex w-full items-center gap-2 rounded-none border-t border-border px-2 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground transition hover:bg-secondary hover:text-foreground disabled:opacity-50"
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
        <h1 className="text-2xl font-bold tracking-tight md:text-3xl">
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
