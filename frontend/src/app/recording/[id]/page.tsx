/**
 * /recording/[id] — the dedicated live-transcription page (Task #14).
 *
 * Replaces the old dismissible RecordModal. Keyed by the `inperson-…` native id
 * (linkable, refresh-addressable). Renders from TWO sources:
 *   - the global `RecordingProvider`'s capture WebSocket (lowest latency) when
 *     THIS tab owns the live session, and
 *   - the backend SSE `/api/meetings/{id}/live` (the `live_segments` buffer) when
 *     it does NOT — i.e. after a hard reload (JS state reset kills the mic/WS) or
 *     for a second viewer with access. That path shows the server-buffered
 *     segments + a clear "recording ended / disconnected" state (no mic control).
 *
 * Meta: elapsed mm:ss · status · speaker count · rolling segment count.
 * Stop → "ending — post-processing" → on the finalize `done` signal, auto-redirect
 * to /meeting/[id] (the #9 inline editor). Cancel/abandon fully tears the session
 * down (no leaked AudioContext / mic tracks). No `beforeunload` warning.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useMemo, useState } from "react";

import { Square } from "lucide-react";

import { AppShell, PageHeader } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import {
  fmt,
  useRecording,
  type LiveSeg,
} from "@/components/recording-provider";
import { ApiError, auth, live, type MeResponse } from "@/lib/api";

type SseState = "connecting" | "live" | "reconnecting";

export default function RecordingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const rec = useRecording();

  const [me, setMe] = useState<MeResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // This tab owns the live session only if the provider is holding THIS id.
  const active = rec.recording && rec.recording.id === id ? rec.recording : null;
  const owned = active !== null;

  // SSE fallback (refresh / second viewer): only when we don't own the WS, or the
  // rows would duplicate the provider's low-latency stream.
  const [sseSegs, setSseSegs] = useState<LiveSeg[]>([]);
  const [sseState, setSseState] = useState<SseState>("connecting");

  // Auth for the AppShell chrome (same pattern as the other pages).
  useEffect(() => {
    let cancelled = false;
    auth
      .me()
      .then((m) => !cancelled && setMe(m))
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setLoadError(err instanceof Error ? err.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (owned) return; // provider WS is the source; SSE would double-render
    const es = live.open(id);
    es.onopen = () => setSseState("live");
    es.onerror = () => setSseState("reconnecting");
    es.onmessage = (e) => {
      try {
        const s = JSON.parse(e.data as string);
        if (s && s.type !== "done") setSseSegs((prev) => [...prev, s as LiveSeg]);
      } catch {
        /* ignore malformed frame */
      }
    };
    return () => es.close();
  }, [owned, id]);

  // On the finalize `done` signal (owner only), hand off to the meeting editor.
  useEffect(() => {
    if (active?.status === "done") {
      rec.clear();
      router.replace(`/meeting/${id}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active?.status, id, router]);

  const segs = owned ? active!.segs : sseSegs;
  const speakerCount = useMemo(
    () => new Set(segs.map((s) => s.speaker)).size,
    [segs],
  );
  // Owner: the live ticker. Non-owner: no start time, so approximate from the
  // latest segment end (seconds-from-start) — good enough for the meta line.
  const elapsed = owned
    ? active!.seconds
    : segs.length
      ? Math.round(Math.max(...segs.map((s) => s.end || 0)))
      : 0;

  if (loadError) return <PageError message={loadError} />;
  if (!me) return <PageLoading />;

  const status: RecordingStatus | "disconnected" = owned
    ? active!.status
    : "disconnected";

  return (
    <AppShell user={me.user}>
      <main className="flex-1 bg-background">
        <div className="mx-auto w-full max-w-3xl px-6 py-8 md:py-10">
          <PageHeader
            title="Live recording"
            subtitle={
              <span className="font-mono text-[11px]">{id}</span>
            }
          />

          {/* ── Status card + controls ── */}
          <div className="rounded-none border border-foreground bg-card p-6 shadow-[4px_4px_0px_0px_rgba(0,0,0,0.15)] dark:shadow-[4px_4px_0px_0px_rgba(255,255,255,0.15)]">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <StatusHeadline status={status} sseState={sseState} />
              {owned &&
              (active!.status === "recording" || active!.status === "starting") ? (
                <div className="flex items-center gap-3">
                  <button
                    onClick={rec.cancel}
                    className="rounded-full px-4 py-2 text-xs font-bold uppercase tracking-wider text-muted-foreground transition hover:text-foreground"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={rec.stop}
                    className="inline-flex items-center gap-2 rounded-full bg-destructive px-5 py-2.5 text-xs font-bold uppercase tracking-wider text-white shadow-lg transition hover:opacity-90 active:scale-95"
                    aria-label="Stop recording"
                  >
                    <Square className="size-4 fill-current" />
                    Stop
                  </button>
                </div>
              ) : null}
              {owned && active!.status === "ending" ? (
                <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  Finalizing — redirecting when ready…
                </span>
              ) : null}
            </div>

            {/* Meta line */}
            <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Meta label="Elapsed">
                <span className="font-mono tabular-nums">{fmt(elapsed)}</span>
              </Meta>
              <Meta label="Status">{statusLabel(status, sseState)}</Meta>
              <Meta label="Speakers">{speakerCount}</Meta>
              <Meta label="Segments">{segs.length}</Meta>
            </dl>

            {owned && active!.error ? (
              <p className="mt-4 rounded-none border border-destructive bg-destructive/10 px-4 py-3 text-xs text-destructive">
                {active!.error}
              </p>
            ) : null}

            {!owned ? (
              <p className="mt-4 rounded-none border border-border bg-secondary/50 px-4 py-3 text-xs text-muted-foreground">
                This view isn&apos;t holding the live mic — you reloaded, or opened
                it on another device. It&apos;s replaying the enclave&apos;s buffered
                live transcript; mic control lives in the tab that started the
                recording.
              </p>
            ) : null}
          </div>

          {/* ── Live segments ── */}
          <div className="mt-6">
            {segs.length > 0 ? (
              <div className="rounded-none border border-border bg-card p-4">
                <ol className="space-y-2">
                  {segs.map((s, i) => (
                    <li key={i} className="text-xs">
                      <span className="font-bold text-primary">{s.speaker}</span>
                      <span className="ml-2 font-mono text-[10px] text-muted-foreground">
                        {s.start.toFixed(1)}–{s.end.toFixed(1)}s
                      </span>
                      <p className="mt-0.5 text-foreground">{s.text}</p>
                    </li>
                  ))}
                </ol>
              </div>
            ) : (
              <p className="rounded-none border border-dashed border-input bg-secondary/40 px-4 py-8 text-center text-xs text-muted-foreground">
                {owned
                  ? "Listening to the room — segments will stream in as people talk."
                  : "No buffered segments yet. If the meeting already finalized, open it from the dashboard."}
              </p>
            )}
          </div>

          <div className="mt-6">
            <Link
              href="/dashboard"
              className="text-xs font-bold uppercase tracking-widest text-muted-foreground transition hover:text-foreground"
            >
              &larr; Back to dashboard
            </Link>
          </div>
        </div>
      </main>
    </AppShell>
  );
}

type RecordingStatus = NonNullable<
  ReturnType<typeof useRecording>["recording"]
>["status"];

function StatusHeadline({
  status,
  sseState,
}: {
  status: RecordingStatus | "disconnected";
  sseState: SseState;
}) {
  if (status === "recording" || status === "starting") {
    return (
      <div className="flex items-center gap-3">
        <span className="size-3 animate-pulse rounded-full bg-destructive" />
        <h2 className="font-heading text-2xl font-black uppercase tracking-tight">
          Recording
        </h2>
      </div>
    );
  }
  if (status === "ending") {
    return (
      <div className="flex items-center gap-3">
        <span className="size-3 animate-pulse rounded-full bg-primary" />
        <h2 className="font-heading text-2xl font-black uppercase tracking-tight">
          Ending — post-processing
        </h2>
      </div>
    );
  }
  if (status === "done") {
    return (
      <h2 className="font-heading text-2xl font-black uppercase tracking-tight">
        Done — opening meeting…
      </h2>
    );
  }
  if (status === "error") {
    return (
      <h2 className="font-heading text-2xl font-black uppercase tracking-tight text-destructive">
        Recording stopped
      </h2>
    );
  }
  // disconnected (non-owner view)
  return (
    <div className="flex items-center gap-3">
      <span
        className={
          sseState === "live"
            ? "size-3 animate-pulse rounded-full bg-attested"
            : "size-3 rounded-full bg-muted-foreground"
        }
      />
      <h2 className="font-heading text-2xl font-black uppercase tracking-tight">
        Disconnected view
      </h2>
    </div>
  );
}

function statusLabel(
  status: RecordingStatus | "disconnected",
  sseState: SseState,
): string {
  switch (status) {
    case "starting":
      return "Requesting mic…";
    case "recording":
      return "Listening";
    case "ending":
      return "Finalizing";
    case "done":
      return "Complete";
    case "error":
      return "Stopped";
    case "disconnected":
      return sseState === "live" ? "Buffered (live)" : "Reconnecting…";
  }
}

function Meta({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-none border border-border bg-secondary/40 px-3 py-2">
      <dt className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm font-bold text-foreground">{children}</dd>
    </div>
  );
}
