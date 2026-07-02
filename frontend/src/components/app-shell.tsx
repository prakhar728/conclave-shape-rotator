/**
 * Signed-in app chrome — Motto Brutalist. A workspace switcher, bordered active
 * nav items, uppercase section labels, a sharp Invite-bot CTA, and the
 * feedback/settings/sign-out block pinned to the bottom. Pages own their headers
 * (see PageHeader).
 *
 * Responsive:
 *  - md+ : a sidebar that COLLAPSES to an icon rail (toggle persisted in
 *    localStorage; labels hidden, `title` tooltips kept).
 *  - <md : a slim top bar with a hamburger that opens the same nav as a
 *    slide-in drawer.
 *
 * Logout hits POST /api/auth/v1/logout which revokes server-side and clears the
 * cookie — the next protected-route hit gets bounced by middleware.ts to /login.
 */
"use client";

import {
  Calendar,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Inbox,
  LayoutGrid,
  ListChecks,
  LogOut,
  Menu,
  MessageSquare,
  Plus,
  Search,
  Settings,
  Share2,
  Tags,
  X,
} from "lucide-react";
import Image from "next/image";
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

const COLLAPSE_KEY = "conclave.sidebar_collapsed";

export function AppShell({
  user,
  children,
}: {
  user: User;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Restore the desktop collapse preference (SSR-safe: runs client-only).
  useEffect(() => {
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      // private mode / no storage — default expanded
    }
  }, []);

  function toggleCollapsed() {
    setCollapsed((v) => {
      const next = !v;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        // ignore
      }
      return next;
    });
  }

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
      {/* ── Desktop sidebar (collapsible) ── */}
      <aside
        className={cn(
          "sticky top-0 z-30 hidden h-screen shrink-0 flex-col border-r border-border bg-sidebar p-4 transition-[width] duration-200 md:flex",
          collapsed ? "w-[4.5rem]" : "w-60",
        )}
      >
        <SidebarBody
          user={user}
          pathname={pathname}
          collapsed={collapsed}
          onLogout={handleLogout}
        />
        {/* Collapse handle — a small arrow riding the divider line, no box. */}
        <button
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
          className="absolute right-0 top-1/2 z-40 flex size-6 -translate-y-1/2 translate-x-1/2 items-center justify-center rounded-full bg-background text-muted-foreground ring-1 ring-border transition hover:bg-foreground hover:text-background hover:ring-foreground"
        >
          {collapsed ? (
            <ChevronRight className="size-3.5" aria-hidden />
          ) : (
            <ChevronLeft className="size-3.5" aria-hidden />
          )}
        </button>
      </aside>

      {/* ── Content column ── */}
      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        {/* Mobile-only slim bar with a hamburger (sidebar is hidden <md). */}
        <header className="flex items-center justify-between border-b border-border bg-card px-4 py-3 md:hidden">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setMobileOpen(true)}
              aria-label="Open menu"
              className="flex size-10 items-center justify-center rounded-none border border-foreground bg-primary text-primary-foreground transition-all hover:bg-muted-foreground active:scale-95"
            >
              <Menu className="size-5" aria-hidden />
            </button>
            <Link href="/dashboard" className="flex items-center gap-2">
              <Image
                src="/logo.png"
                alt="Conclave logo"
                width={28}
                height={28}
                className="size-7 rounded-none object-contain"
              />
              <span className="text-sm font-bold tracking-tight">Conclave</span>
            </Link>
          </div>
          <RecordingIndicator compact />
        </header>
        {children}
      </div>

      {/* ── Mobile drawer ── */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-[80] md:hidden">
          <div
            className="absolute inset-0 bg-foreground/40 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <aside className="absolute left-0 top-0 flex h-full w-72 max-w-[85%] flex-col border-r border-foreground bg-sidebar p-4">
            <div className="mb-4 flex items-center justify-between">
              <span className="text-xs font-black uppercase tracking-widest text-muted-foreground">
                Menu
              </span>
              <button
                onClick={() => setMobileOpen(false)}
                aria-label="Close menu"
                className="flex size-8 items-center justify-center rounded-none border border-border bg-card transition hover:bg-secondary"
              >
                <X className="size-4" aria-hidden />
              </button>
            </div>
            <SidebarBody
              user={user}
              pathname={pathname}
              collapsed={false}
              onLogout={handleLogout}
              onNavigate={() => setMobileOpen(false)}
            />
          </aside>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The sidebar contents, shared by the desktop rail and the mobile drawer.
 * `collapsed` renders an icon-only rail (labels hidden, tooltips kept);
 * `onNavigate` (mobile) closes the drawer on any link tap; `onToggle` (desktop)
 * shows the collapse/expand control.
 */
function SidebarBody({
  user,
  pathname,
  collapsed,
  onLogout,
  onNavigate,
}: {
  user: User;
  pathname: string;
  collapsed: boolean;
  onLogout: () => void;
  onNavigate?: () => void;
}) {
  return (
    <>
      <div className="mb-8">
        <WorkspaceSwitcher collapsed={collapsed} />
      </div>

      <RecordingIndicator compact={collapsed} />

      <nav className="space-y-1.5">
        {NAV.map(({ href, label, icon: Icon }) => (
          <NavRow
            key={href}
            href={href}
            label={label}
            Icon={Icon}
            active={pathname.startsWith(href)}
            collapsed={collapsed}
            onNavigate={onNavigate}
          />
        ))}
      </nav>

      <div className="mt-4 border-t border-border pt-4">
        <Link
          href="/invite"
          onClick={onNavigate}
          title={collapsed ? "Invite bot" : undefined}
          className={cn(
            "flex items-center gap-3 rounded-lg py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground",
            collapsed ? "justify-center px-0" : "px-3",
          )}
        >
          <Plus className="size-4 shrink-0" aria-hidden />
          {!collapsed && "Invite bot"}
        </Link>
      </div>

      <div className="mt-auto space-y-3 border-t border-border pt-4">
        <NavRow
          href={`/feedback?from=${encodeURIComponent(pathname)}`}
          label="Feedback"
          Icon={MessageSquare}
          active={pathname.startsWith("/feedback")}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
        {user.is_admin ? (
          <NavRow
            href="/admin/feedback"
            label="Feedback inbox"
            Icon={Inbox}
            active={pathname.startsWith("/admin/feedback")}
            collapsed={collapsed}
            onNavigate={onNavigate}
          />
        ) : null}
        <NavRow
          href="/settings"
          label="Settings"
          Icon={Settings}
          active={pathname.startsWith("/settings")}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
        {!collapsed ? (
          <p className="truncate px-3 text-xs text-muted-foreground">
            {user.email}
          </p>
        ) : null}
        <button
          onClick={onLogout}
          title={collapsed ? "Sign out" : undefined}
          className={cn(
            "flex w-full items-center gap-3 rounded-lg py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary/60 hover:text-foreground",
            collapsed ? "justify-center px-0" : "px-3",
          )}
        >
          <LogOut className="size-3.5 shrink-0" aria-hidden />
          {!collapsed && "Sign out"}
        </button>
      </div>
    </>
  );
}

/** One nav row — icon + label, or icon-only (with tooltip) when collapsed. */
function NavRow({
  href,
  label,
  Icon,
  active,
  collapsed,
  onNavigate,
}: {
  href: string;
  label: string;
  Icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  active: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      title={collapsed ? label : undefined}
      className={cn(
        "flex items-center gap-3 rounded-lg py-2 text-sm font-medium transition-colors",
        collapsed ? "justify-center px-0" : "px-3",
        active
          ? "bg-secondary text-foreground font-semibold"
          : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
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
        title={ending ? "Ending meeting…" : "Recording"}
        className="mb-3 inline-flex items-center justify-center gap-1.5 rounded-none border border-destructive bg-destructive/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-destructive"
      >
        <span className="size-2 animate-pulse rounded-full bg-destructive" />
        {ending ? "End" : fmt(recording.seconds)}
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
 * Sidebar workspace switcher: brutalist dropdown. Collapses to a logo-only
 * button (the dropdown still opens with full workspace names).
 */
function WorkspaceSwitcher({ collapsed = false }: { collapsed?: boolean }) {
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
    <div ref={boxRef} className="relative min-w-0 flex-1">
      <button
        onClick={() => setOpen((v) => !v)}
        title={collapsed ? (workspace?.name ?? "Conclave") : undefined}
        className={cn(
          "flex w-full items-center gap-3 rounded-lg p-2.5 text-left transition hover:bg-secondary/60",
          collapsed && "justify-center p-1.5",
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <Image
          src="/logo.png"
          alt="Conclave logo"
          width={32}
          height={32}
          className="size-8 shrink-0 rounded-lg object-contain"
        />
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1 truncate text-sm font-semibold">
              {workspace?.name ?? (workspaces === null ? "…" : "Conclave")}
            </span>
            <ChevronsUpDown
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-hidden
            />
          </>
        )}
      </button>

      {open ? (
        <div
          role="listbox"
          className="absolute left-0 top-full z-50 mt-1.5 min-w-52 origin-top overflow-hidden rounded-lg border border-border bg-card p-1 animate-in fade-in-0 zoom-in-95 slide-in-from-top-1 duration-150"
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
              className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm font-medium transition hover:bg-secondary"
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
            className="mt-1 flex w-full items-center gap-2 rounded-md border-t border-border px-2 py-2 text-left text-sm font-medium text-muted-foreground transition hover:bg-secondary hover:text-foreground disabled:opacity-50"
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
 * Page header: bold headline + optional subtext, with icon-button actions on
 * the right (global search lives here now that there is no topbar).
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
