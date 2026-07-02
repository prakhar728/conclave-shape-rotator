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
 * The header is a single voice widget (`AIVoiceInput`): its spinning square is
 * the recording indicator AND the stop control, the mono timer is the elapsed
 * clock, and the bars are the live mic amplitude (from the provider's analyser).
 * Stop → "Finalizing" → on the finalize `done` signal, auto-redirect to
 * /meeting/[id] (the #9 inline editor). Cancel/abandon fully tears the session
 * down (no leaked AudioContext / mic tracks). No `beforeunload` warning.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { AppShell, PageHeader } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { fmt, useRecording, type LiveSeg } from "@/components/recording-provider";
import { AIVoiceInput } from "@/components/ui/ai-voice-input";
import { ApiError, auth, live, type MeResponse } from "@/lib/api";
import { speakerLabel } from "@/lib/speakerLabel";
import { groupIntoTurns } from "@/lib/turns";

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
  // Owner: the live ticker. Non-owner: no start time, so approximate from the
  // latest segment end (seconds-from-start) — good enough for the header clock.
  const elapsed = owned
    ? active!.seconds
    : segs.length
      ? Math.round(Math.max(...segs.map((s) => s.end || 0)))
      : 0;

  if (loadError) return <PageError message={loadError} />;
  if (!me) return <PageLoading />;

  const micActive =
    owned &&
    (active!.status === "starting" ||
      active!.status === "recording" ||
      active!.status === "ending");
  const canStop =
    owned && (active!.status === "recording" || active!.status === "starting");
  const statusText = owned
    ? active!.status === "starting"
      ? "Requesting mic"
      : active!.status === "recording"
        ? "Listening"
        : active!.status === "ending"
          ? "Finalizing"
          : active!.status === "done"
            ? "Opening meeting"
            : ""
    : "";

  return (
    <AppShell user={me.user}>
      <main className="flex-1 bg-background">
        <div className="mx-auto w-full max-w-3xl px-6 py-8 md:py-10">
          <PageHeader
            title="Live recording"
            subtitle={<span className="font-mono text-[11px]">{id}</span>}
          />

          {/* ── Voice widget: indicator + timer + live amplitude + stop ── */}
          {owned && active!.status === "error" ? (
            <div className="rounded-xl border border-destructive/50 bg-destructive/5 px-5 py-4 text-center">
              <p className="text-sm font-medium text-destructive">Recording stopped</p>
              {active!.error ? (
                <p className="mt-1 text-xs text-muted-foreground">{active!.error}</p>
              ) : null}
            </div>
          ) : owned ? (
            <div className="flex flex-col items-center gap-2 rounded-2xl bg-muted/50 py-8 shadow-sm">
              <AIVoiceInput
                active={micActive}
                elapsedSeconds={elapsed}
                getLevels={rec.getAudioLevels}
                statusText={statusText}
                ariaLabel={canStop ? "Stop recording" : undefined}
                onToggle={canStop ? rec.stop : undefined}
                visualizerBars={56}
              />
              {canStop ? (
                <button
                  onClick={rec.cancel}
                  className="text-xs text-muted-foreground transition hover:text-foreground"
                >
                  Cancel
                </button>
              ) : null}
            </div>
          ) : (
            <div className="flex flex-col items-center gap-1 rounded-2xl bg-muted/50 py-10 text-center shadow-sm">
              <span className="font-mono text-sm tabular-nums text-muted-foreground">
                {fmt(elapsed)}
              </span>
              <p className="text-sm font-medium text-foreground">Disconnected view</p>
              <p className="max-w-sm px-6 text-xs text-muted-foreground">
                {sseState === "live" ? "Replaying the buffered live transcript. " : "Reconnecting. "}
                Mic control lives in the tab that started the recording.
              </p>
            </div>
          )}

          {/* ── Live segments ── */}
          <div className="mt-8 border-t border-border/60 pt-6">
            <h2 className="mb-4 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Live transcript
            </h2>
            {segs.length > 0 ? (
              <ol className="space-y-3">
                {/* Task #37 — coalesce consecutive same-speaker spans into turns; the
                    open (last) turn GROWS as new spans stream, closes on a speaker flip. */}
                {groupIntoTurns(segs).map((turn, i) => (
                  <li key={i} className="text-sm">
                    <span className="font-semibold text-primary">
                      {speakerLabel(turn.speaker)}
                    </span>
                    <p className="mt-0.5 whitespace-pre-line text-foreground">{turn.text}</p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="rounded-xl bg-muted/40 px-4 py-10 text-center text-sm text-muted-foreground">
                {owned
                  ? "Listening to the room. Segments will stream in as people talk."
                  : "No buffered segments yet. If the meeting already finalized, open it from the dashboard."}
              </p>
            )}
          </div>

          <div className="mt-8">
            <Link
              href="/dashboard"
              className="text-xs text-muted-foreground transition hover:text-foreground"
            >
              Back to dashboard
            </Link>
          </div>
        </div>
      </main>
    </AppShell>
  );
}
