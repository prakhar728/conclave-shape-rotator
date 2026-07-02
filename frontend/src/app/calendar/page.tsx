/**
 * /calendar — connect Google Calendar and pick which meetings Conclave should
 * auto-record. The same controls also live under /settings; this is the
 * dedicated, sidebar-reachable view.
 */
"use client";

import { CalendarDays } from "lucide-react";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { CalendarSettings } from "@/components/calendar-settings";
import { PageError, PageLoading } from "@/components/page-state";
import { auth, type MeResponse } from "@/lib/api";

export default function CalendarPage() {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const m = await auth.me();
        if (!cancelled) setMe(m);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error && !me) return <PageError message={error} />;
  if (!me) return <PageLoading />;

  return (
    <AppShell user={me.user}>
      <main className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <CalendarDays className="size-6 shrink-0 text-muted-foreground" aria-hidden />
          Calendar
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect your Google Calendar and choose which meetings Conclave should
          automatically send a recording bot to.
        </p>
        <CalendarSettings />
      </main>
    </AppShell>
  );
}
