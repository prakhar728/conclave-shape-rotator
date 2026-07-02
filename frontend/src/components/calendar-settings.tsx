/**
 * Google Calendar integration — connect + per-event auto-record.
 *
 * Connect starts the OAuth flow (GET /api/calendar/connect → { auth_url }) and
 * sends the browser to Google's consent screen. The backend stores encrypted
 * tokens and redirects back (set CONCLAVE_CALENDAR_POST_CONNECT_URL=/settings to
 * land here). When connected, lists upcoming meetings; flipping "Auto-record"
 * opts an event into the background poller, which dispatches a capture bot to its
 * Meet at start time. Auto-record needs a Google Meet link on the event and a
 * selected workspace (that's where the transcript lands).
 */
"use client";

import { useCallback, useEffect, useState } from "react";

import { useWorkspace } from "@/components/workspace-provider";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  calendar,
  type CalendarEvent,
  type CalendarStatus,
} from "@/lib/api";

function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function CalendarSettings() {
  const { workspace } = useWorkspace();
  const workspaceId = workspace?.id ?? null;

  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [events, setEvents] = useState<CalendarEvent[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const loadEvents = useCallback(async () => {
    setEvents(null);
    try {
      const r = await calendar.events();
      setEvents(r.events);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load events");
      setEvents([]);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Post-connect redirect flag — read client-side here (inside the async
      // body) so it isn't a synchronous setState in the effect body, and to
      // avoid useSearchParams' prerender Suspense requirement.
      const flag = new URLSearchParams(window.location.search).get("calendar");
      if (flag === "connected") setNote("Google Calendar connected.");
      else if (flag === "denied") setNote("Connection was cancelled.");
      try {
        const s = await calendar.status();
        if (cancelled) return;
        setStatus(s);
        if (s.connected) await loadEvents();
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 503) {
          setStatus({ connected: false });
          setError("Calendar isn't configured on the server.");
        } else {
          setError(e instanceof Error ? e.message : "Failed to load calendar status");
          setStatus({ connected: false });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadEvents]);

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      const { auth_url } = await calendar.connect();
      window.location.href = auth_url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start Google connect");
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    setBusy(true);
    setError(null);
    try {
      await calendar.disconnect();
      setStatus({ connected: false });
      setEvents(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disconnect");
    } finally {
      setBusy(false);
    }
  }

  async function toggleAutoRecord(ev: CalendarEvent, next: boolean) {
    if (!workspaceId) {
      setError("Select a workspace first — that's where the transcript lands.");
      return;
    }
    setPendingId(ev.id);
    setError(null);
    setEvents((prev) =>
      prev ? prev.map((e) => (e.id === ev.id ? { ...e, auto_record: next } : e)) : prev,
    );
    try {
      await calendar.setAutoRecord(ev.id, next, workspaceId);
    } catch (e) {
      // Revert the optimistic flip.
      setEvents((prev) =>
        prev ? prev.map((e) => (e.id === ev.id ? { ...e, auto_record: !next } : e)) : prev,
      );
      const msg =
        e instanceof ApiError && e.status === 422
          ? "That event has no Google Meet link — can't auto-record."
          : e instanceof Error
            ? e.message
            : "Failed to update auto-record";
      setError(msg);
    } finally {
      setPendingId(null);
    }
  }

  async function toggleRecordAll(next: boolean) {
    if (!workspaceId) {
      setError("Select a workspace first — that's where transcripts land.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await calendar.setAutoRecordAll(next, workspaceId);
      setStatus((prev) =>
        prev && prev.connected
          ? { ...prev, auto_record_all: next ? workspaceId : null }
          : prev,
      );
      // Per-event "effective" auto-record state changes — refresh the list.
      await loadEvents();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 rounded-none border border-border bg-card p-5">
      <h2 className="text-sm font-medium">Google Calendar</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Connect your calendar so Conclave can automatically send a recording bot
        to the meetings you opt in.
      </p>

      {note ? <p className="mt-3 text-xs text-muted-foreground">{note}</p> : null}

      {status === null ? (
        <p className="mt-4 text-xs text-muted-foreground">Loading…</p>
      ) : !status.connected ? (
        <div className="mt-4">
          <Button onClick={handleConnect} disabled={busy}>
            {busy ? "Redirecting…" : "Connect Google Calendar"}
          </Button>
        </div>
      ) : (
        <div className="mt-4">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">
              Connected
              {status.connected_at ? ` · ${formatWhen(status.connected_at)}` : ""}
            </span>
            <Button variant="outline" onClick={handleDisconnect} disabled={busy}>
              Disconnect
            </Button>
          </div>

          <label className="mt-4 flex items-center justify-between gap-3 rounded-none border border-border px-3 py-2.5">
            <span className="min-w-0">
              <span className="block text-xs font-medium text-foreground">
                Auto-record all my meetings
              </span>
              <span className="block text-[11px] text-muted-foreground">
                Record every Google Meet on your calendar (you can still turn off
                individual ones below).
              </span>
            </span>
            <input
              type="checkbox"
              checked={status.auto_record_all !== null}
              disabled={!workspaceId || busy}
              onChange={(e) => toggleRecordAll(e.target.checked)}
              className="size-4 shrink-0 accent-primary disabled:opacity-40"
              aria-label="Auto-record all my meetings"
            />
          </label>

          {!workspaceId ? (
            <p className="mt-3 text-xs text-destructive">
              No workspace selected — pick one to enable auto-record.
            </p>
          ) : null}

          <div className="mt-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-medium">Upcoming meetings (next 7 days)</h3>
              <button
                type="button"
                onClick={loadEvents}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Refresh
              </button>
            </div>

            {events === null ? (
              <p className="mt-2 text-xs text-muted-foreground">Loading events…</p>
            ) : events.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">
                No upcoming meetings found.
              </p>
            ) : (
              <ul className="mt-2 divide-y divide-border rounded-none border border-border">
                {events.map((ev) => {
                  const hasMeet = Boolean(ev.hangout_link);
                  return (
                    <li
                      key={ev.id}
                      className="flex items-center justify-between gap-3 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm text-foreground">{ev.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatWhen(ev.start)}
                          {hasMeet ? "" : " · no Meet link"}
                        </p>
                      </div>
                      <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
                        Auto-record
                        <input
                          type="checkbox"
                          checked={ev.auto_record}
                          disabled={!hasMeet || !workspaceId || pendingId === ev.id}
                          onChange={(e) => toggleAutoRecord(ev, e.target.checked)}
                          className="h-4 w-4 accent-primary disabled:opacity-40"
                          aria-label={`Auto-record ${ev.title}`}
                        />
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}

      {error ? <p className="mt-3 text-xs text-destructive">{error}</p> : null}
    </section>
  );
}
