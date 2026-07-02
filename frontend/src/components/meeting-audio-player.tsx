/**
 * Meeting-page audio player (Task #30).
 *
 * Streams the full meeting recording from the decrypt-on-read endpoint
 * (`/api/transcripts/sessions/{id}/audio`). Cookie auth is same-origin, so the
 * URL is used directly as the <audio> src — the backend decrypts in memory and
 * never writes plaintext back to disk. The native <audio> element is the media
 * engine but stays hidden; the visible controls are a custom skin.
 *
 * Waveform: a second same-origin fetch pulls the bytes once more and decodes
 * per-bar peaks via the Web Audio API, drawn as bars that double as the
 * scrubber. It is a progressive enhancement — if decode is unavailable or fails
 * (jsdom, legacy codec) we quietly fall back to a plain progress line. Only the
 * <audio> onError self-hides the whole player; a waveform failure never does.
 *
 * Self-hiding: renders nothing when the meeting explicitly opted out of storing
 * audio (`storeAudio === false`), after the owner deletes it, or when the fetch
 * 404s (no audio / legacy session) via the <audio> onError. The owner gets a
 * quiet trash control (transcript + insights are untouched).
 */
"use client";

import { Pause, Play, Trash2, Volume2, VolumeX } from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

import { meetings as meetingsApi } from "@/lib/api";

const WAVEFORM_BARS = 96;

/**
 * Imperative handle exposed to the meeting page (Task #41 click-to-seek):
 * `seekTo(seconds)` moves the playhead and starts playback. A no-op when the
 * media element isn't mounted (audio opted-out / deleted / 404 self-hide).
 */
export type MeetingAudioPlayerHandle = {
  seekTo: (seconds: number) => void;
};

function fmtTime(seconds: number): string {
  const s = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  const m = Math.floor(s / 60);
  return `${m}:${(s % 60).toString().padStart(2, "0")}`;
}

/** Downsample a decoded buffer to `bars` normalized (0..1) peak heights. */
function computePeaks(buffer: AudioBuffer, bars: number): number[] {
  const data = buffer.getChannelData(0);
  const block = Math.floor(data.length / bars) || 1;
  const peaks: number[] = [];
  for (let i = 0; i < bars; i++) {
    let max = 0;
    const start = i * block;
    for (let j = 0; j < block; j++) {
      const v = Math.abs(data[start + j] ?? 0);
      if (v > max) max = v;
    }
    peaks.push(max);
  }
  const loudest = Math.max(...peaks, 0.0001);
  return peaks.map((p) => p / loudest);
}

export const MeetingAudioPlayer = forwardRef<
  MeetingAudioPlayerHandle,
  {
    sessionId: string;
    isOwner?: boolean;
    storeAudio?: boolean | null;
    // Task #41 — called with whether the meeting has playable audio (true once
    // <audio> metadata loads, false when the player self-hides / opts out). Lets
    // the meeting page make transcript segments seek-clickable only when useful.
    onAvailabilityChange?: (available: boolean) => void;
  }
>(function MeetingAudioPlayer(
  { sessionId, isOwner = false, storeAudio, onAvailabilityChange },
  ref,
) {
  const [gone, setGone] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);

  // Task #41 — imperative seek used by transcript click-to-seek. Clamp to >= 0;
  // duration is enforced by the media element. Starts playback so a click both
  // jumps and plays.
  useImperativeHandle(
    ref,
    () => ({
      seekTo(seconds: number) {
        const a = audioRef.current;
        if (!a) return;
        const t = Math.max(0, seconds);
        a.currentTime = t;
        setCurrent(t);
        void a.play();
      },
    }),
    [],
  );

  // Task #41 — report loss of availability (opted out / deleted / 404 self-hide)
  // so the page stops offering seek affordances. Availability becomes true from
  // the <audio> onLoadedMetadata handler below.
  useEffect(() => {
    if (storeAudio === false || gone) onAvailabilityChange?.(false);
  }, [storeAudio, gone, onAvailabilityChange]);

  // Decode the recording into a static waveform (best-effort, never self-hides).
  useEffect(() => {
    if (storeAudio === false) return;
    let cancelled = false;
    (async () => {
      try {
        const AC =
          window.AudioContext ??
          (window as unknown as { webkitAudioContext?: typeof AudioContext })
            .webkitAudioContext;
        if (!AC) return;
        const res = await fetch(meetingsApi.audioUrl(sessionId), {
          credentials: "same-origin",
        });
        if (!res.ok) return;
        const bytes = await res.arrayBuffer();
        if (cancelled) return;
        const ctx = new AC();
        const decoded = await ctx.decodeAudioData(bytes);
        void ctx.close();
        if (cancelled) return;
        setPeaks(computePeaks(decoded, WAVEFORM_BARS));
      } catch {
        /* leave peaks null → plain-line fallback */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, storeAudio]);

  const toggle = useCallback(() => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) {
      void a.play();
    } else {
      a.pause();
    }
  }, []);

  const seekToClientX = useCallback(
    (clientX: number) => {
      const el = trackRef.current;
      const a = audioRef.current;
      if (!el || !a || !duration) return;
      const rect = el.getBoundingClientRect();
      const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      a.currentTime = pct * duration;
      setCurrent(pct * duration);
    },
    [duration],
  );

  const onTrackPointerDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      seekToClientX(e.clientX);
      const move = (ev: PointerEvent) => seekToClientX(ev.clientX);
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    },
    [seekToClientX],
  );

  const onDelete = useCallback(async () => {
    if (!window.confirm("Delete this meeting's audio? The transcript and insights stay.")) {
      return;
    }
    setDeleting(true);
    try {
      await meetingsApi.deleteAudio(sessionId);
      setGone(true);
    } catch {
      setDeleting(false);
    }
  }, [sessionId]);

  if (storeAudio === false || gone) return null;

  const frac = duration > 0 ? current / duration : 0;
  const pct = frac * 100;

  return (
    <div className="flex items-center gap-4">
      <audio
        ref={audioRef}
        preload="metadata"
        src={meetingsApi.audioUrl(sessionId)}
        onError={() => setGone(true)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          setDuration(e.currentTarget.duration);
          onAvailabilityChange?.(true); // Task #41 — audio is playable/seekable
        }}
        className="hidden"
      >
        Your browser does not support audio playback.
      </audio>

      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? "Pause" : "Play"}
        className="flex size-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition hover:opacity-90 active:scale-95"
      >
        {playing ? (
          <Pause className="size-4" fill="currentColor" strokeWidth={0} />
        ) : (
          <Play className="size-4 translate-x-px" fill="currentColor" strokeWidth={0} />
        )}
      </button>

      <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
        {fmtTime(current)} / {fmtTime(duration)}
      </span>

      {peaks ? (
        <div
          ref={trackRef}
          onPointerDown={onTrackPointerDown}
          className="flex h-10 flex-1 cursor-pointer items-center gap-px"
        >
          {peaks.map((p, i) => {
            const played = (i + 0.5) / peaks.length <= frac;
            return (
              <div
                key={i}
                className={`flex-1 rounded-full transition-colors ${
                  played ? "bg-foreground" : "bg-muted"
                }`}
                style={{ height: `${Math.max(8, p * 100)}%` }}
              />
            );
          })}
        </div>
      ) : (
        <div
          ref={trackRef}
          onPointerDown={onTrackPointerDown}
          className="group relative flex h-4 flex-1 cursor-pointer items-center"
        >
          <div className="h-1 w-full rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-foreground/80"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div
            className="absolute size-3 -translate-x-1/2 rounded-full bg-foreground opacity-0 shadow transition group-hover:opacity-100"
            style={{ left: `${pct}%` }}
          />
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          const a = audioRef.current;
          if (!a) return;
          a.muted = !a.muted;
          setMuted(a.muted);
        }}
        aria-label={muted ? "Unmute" : "Mute"}
        className="shrink-0 text-muted-foreground transition hover:text-foreground"
      >
        {muted ? <VolumeX className="size-4" /> : <Volume2 className="size-4" />}
      </button>

      {isOwner ? (
        <button
          type="button"
          onClick={onDelete}
          disabled={deleting}
          aria-label="Delete audio"
          title="Delete audio"
          className="shrink-0 text-muted-foreground transition hover:text-destructive disabled:opacity-50"
        >
          <Trash2 className="size-4" />
        </button>
      ) : null}
    </div>
  );
});
