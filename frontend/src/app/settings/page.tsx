/**
 * /settings — account preferences (Transcript Saving, Phase 2).
 *
 * Today it holds the account-wide transcript retention default. "Keep forever"
 * is null; a day count auto-deletes each transcript's RAW text that many days
 * after it was created (the summary + knowledge graph are always kept). Any
 * meeting can override this on its own page.
 */
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/app-shell";
import { CalendarSettings } from "@/components/calendar-settings";
import { DataExportControl } from "@/components/data-export-control";
import { TncNotice } from "@/components/tnc-notice";
import { PageError, PageLoading } from "@/components/page-state";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  auth,
  userSettings,
  type MeResponse,
} from "@/lib/api";

// null = keep forever; the rest are day counts.
const RETENTION_OPTIONS: { value: number | null; label: string }[] = [
  { value: null, label: "Keep forever" },
  { value: 30, label: "Auto-delete after 30 days" },
  { value: 90, label: "Auto-delete after 90 days" },
  { value: 365, label: "Auto-delete after 1 year" },
];

export default function SettingsPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [retentionDays, setRetentionDays] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [meResp, settings] = await Promise.all([
          auth.me(),
          userSettings.get(),
        ]);
        if (cancelled) return;
        setMe(meResp);
        setRetentionDays(settings.retention_days);
        setLoaded(true);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load settings");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleSave() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const r = await userSettings.update(retentionDays);
      setRetentionDays(r.retention_days);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setBusy(false);
    }
  }

  if (error && !me) return <PageError message={error} />;
  if (!me || !loaded) return <PageLoading />;

  return (
    <AppShell user={me.user}>
      <main className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>

        <section className="mt-8 rounded-lg border border-border bg-card p-5">
          <h2 className="text-sm font-medium">Transcript retention</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Choose how long to keep the raw transcript of your meetings. When a
            transcript auto-deletes, the meeting summary and everything derived
            from it are kept — only the verbatim transcript is removed. You can
            override this on any individual meeting.
          </p>

          <select
            value={retentionDays === null ? "null" : String(retentionDays)}
            onChange={(e) => {
              setSaved(false);
              setRetentionDays(
                e.target.value === "null" ? null : Number(e.target.value),
              );
            }}
            disabled={busy}
            aria-label="Default transcript retention"
            className="mt-4 h-9 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground"
          >
            {RETENTION_OPTIONS.map((o) => (
              <option key={String(o.value)} value={o.value === null ? "null" : String(o.value)}>
                {o.label}
              </option>
            ))}
          </select>

          <div className="mt-4 flex items-center gap-3">
            <Button onClick={handleSave} disabled={busy}>
              {busy ? "Saving…" : "Save"}
            </Button>
            {saved ? (
              <span className="text-xs text-muted-foreground">Saved.</span>
            ) : null}
            {error ? (
              <span className="text-xs text-destructive">{error}</span>
            ) : null}
          </div>
        </section>

        <CalendarSettings />

        <DataExportControl />

        <TncNotice />
      </main>
    </AppShell>
  );
}
