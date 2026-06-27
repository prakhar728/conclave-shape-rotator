/**
 * In-person Record — orange pill CTA + modal (Vantage language, sibling of
 * UploadTranscriptButton).
 *
 * MIGRATED (live capture): instead of MediaRecorder→upload→/api/workspaces/{id}/record (where Conclave
 * itself transcribed + diarized), this now STREAMS the room mic to the capture microservice over a
 * WebSocket. capture diarizes live (diart) + transcribes each span (NEAR Whisper) and publishes
 * `[local_speaker] text` to Redis, which Conclave ingests — so the transcription PROCESS lives in capture;
 * Conclave only displays. The modal shows the diart live transcript as it streams. On Stop, capture
 * uploads the recording + fires Conclave's meeting-completed webhook (finalize → DiariZen authoritative +
 * VFTE identity), then we navigate to /meeting/[id] where the diart transcript shows immediately and
 * swaps to the authoritative version once post-processing completes.
 *
 * The legacy POST /api/workspaces/{id}/record endpoint still exists server-side (API/upload), but the UI
 * no longer uses it. This is Conclave ingress mode 3 (bot · upload · record).
 */
"use client";

import { Mic, Square, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import { cn } from "@/lib/utils";

// capture's in-person WebSocket base (e.g. ws://localhost:8087) + the engine token. Public env so the
// browser can reach capture directly; in production this is capture's edge URL + a per-session token.
const CAPTURE_WS_BASE =
  process.env.NEXT_PUBLIC_CAPTURE_INPERSON_WS_URL || "ws://localhost:8087";
const CAPTURE_TOKEN = process.env.NEXT_PUBLIC_CAPTURE_DIARIZE_TOKEN || "dev-diarize-token";

// AudioWorklet that emits 16 kHz mono int16 frames (8000 samples ≈ 0.5 s) — same as capture's reference
// inperson_mic.html so the wire format matches the /v1/inperson/stream contract exactly.
const WORKLET = `
class PCMEmitter extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Int16Array(8000); this.i = 0; }
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    for (let k = 0; k < ch.length; k++) {
      let s = Math.max(-1, Math.min(1, ch[k]));
      this.buf[this.i++] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      if (this.i === this.buf.length) { this.port.postMessage(this.buf.slice().buffer); this.i = 0; }
    }
    return true;
  }
}
registerProcessor('pcm-emitter', PCMEmitter);
`;

type LiveSeg = { start: number; end: number; speaker: string; text?: string };

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function newMeetingId(): string {
  const rand = Math.random().toString(36).slice(2, 8);
  return `inperson-${Date.now()}-${rand}`;
}

export function RecordMeetingButton({
  workspaceId,
  className,
}: {
  workspaceId: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className={cn(
          "inline-flex h-10 items-center gap-2 rounded-full bg-primary px-5 text-xs font-bold text-primary-foreground shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 active:scale-95",
          className,
        )}
      >
        <Mic className="size-4" aria-hidden />
        Record meeting
      </button>
      {open ? (
        <RecordModal workspaceId={workspaceId} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}

function RecordModal({
  workspaceId,
  onClose,
}: {
  workspaceId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const [recording, setRecording] = useState(false);
  const [ending, setEnding] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [status, setStatus] = useState("Tap the mic to start");
  const [error, setError] = useState<string | null>(null);
  const [segs, setSegs] = useState<LiveSeg[]>([]);

  const ctxRef = useRef<AudioContext | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sockRef = useRef<WebSocket | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const meetingIdRef = useRef<string>("");

  const teardown = useCallback(() => {
    try { nodeRef.current?.disconnect(); } catch {}
    try { ctxRef.current?.close(); } catch {}
    try { streamRef.current?.getTracks().forEach((t) => t.stop()); } catch {}
    if (tickRef.current) clearInterval(tickRef.current);
    nodeRef.current = null;
    ctxRef.current = null;
    streamRef.current = null;
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setSegs([]);
    const uid = newMeetingId();
    meetingIdRef.current = uid;
    const url =
      `${CAPTURE_WS_BASE.replace(/\/$/, "")}/v1/inperson/stream` +
      `?uid=${encodeURIComponent(uid)}&workspace=${encodeURIComponent(workspaceId)}` +
      `&token=${encodeURIComponent(CAPTURE_TOKEN)}`;
    try {
      setStatus("Requesting mic…");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
      streamRef.current = stream;
      const ctx = new AudioContext({ sampleRate: 16000 });
      ctxRef.current = ctx;
      await ctx.audioWorklet.addModule(
        URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" })),
      );
      const node = new AudioWorkletNode(ctx, "pcm-emitter");
      nodeRef.current = node;
      const sink = ctx.createGain();
      sink.gain.value = 0;
      ctx.createMediaStreamSource(stream).connect(node);
      node.connect(sink).connect(ctx.destination);

      const sock = new WebSocket(url);
      sock.binaryType = "arraybuffer";
      sockRef.current = sock;
      sock.onopen = () => {
        node.port.onmessage = (e) => {
          if (sock.readyState === 1) sock.send(e.data as ArrayBuffer);
        };
        setRecording(true);
        setSeconds(0);
        setStatus("Recording — listening to the room");
        tickRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
      };
      sock.onmessage = (e) => {
        const m = JSON.parse(e.data as string);
        if (m.type === "done") {
          // capture has uploaded the recording + fired Conclave's finalize webhook → safe to navigate.
          teardown();
          router.push(`/meeting/${meetingIdRef.current}`);
          return;
        }
        setSegs((prev) => [...prev, m as LiveSeg]);
      };
      sock.onerror = () => setError("Connection to the capture service failed (token / service up?).");
      sock.onclose = (ev) => {
        if (ev.code === 1008) setError("Rejected — bad or missing capture token.");
        if (!ending) {
          setRecording(false);
          if (tickRef.current) clearInterval(tickRef.current);
        }
      };
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start recording");
      teardown();
      setRecording(false);
    }
  }, [workspaceId, router, teardown, ending]);

  const stop = useCallback(() => {
    const sock = sockRef.current;
    if (sock && sock.readyState === 1) {
      setEnding(true);
      setRecording(false);
      setStatus("Ending meeting — post-processing…");
      if (tickRef.current) clearInterval(tickRef.current);
      sock.send(new ArrayBuffer(0)); // empty frame = meeting-end (capture uploads + fires the webhook)
    } else {
      teardown();
      onClose();
    }
  }, [teardown, onClose]);

  function close() {
    if (recording || ending) {
      const sock = sockRef.current;
      if (sock && sock.readyState === 1) sock.send(new ArrayBuffer(0));
    }
    teardown();
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm"
      onClick={close}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Record meeting"
        className="flex max-h-[88vh] w-full max-w-lg flex-col rounded-3xl border border-border bg-card p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold tracking-tight">
              Record an in-person meeting
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Streamed live to the enclave — speakers are separated and transcribed as you talk. After you
              stop, the recording is re-diarized for the final transcript and consented speakers are named.
            </p>
          </div>
          <button
            onClick={close}
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-muted-foreground transition hover:text-foreground"
            aria-label="Close"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Record control */}
        <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-input bg-secondary/50 p-6 text-center">
          {!recording ? (
            <button
              onClick={start}
              disabled={ending}
              className="flex size-16 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg shadow-primary/20 transition hover:bg-primary/90 active:scale-95 disabled:opacity-50"
              aria-label="Start recording"
            >
              <Mic className="size-7" />
            </button>
          ) : (
            <button
              onClick={stop}
              className="flex size-16 items-center justify-center rounded-full bg-destructive text-white shadow-lg transition hover:opacity-90 active:scale-95"
              aria-label="Stop recording"
            >
              <Square className="size-6 fill-current" />
            </button>
          )}
          <div className="flex items-center gap-2 font-mono text-sm tabular-nums text-muted-foreground">
            {recording ? (
              <span className="size-2 animate-pulse rounded-full bg-destructive" />
            ) : null}
            {fmt(seconds)}
          </div>
          <p className="text-[11px] text-muted-foreground">{status}</p>
        </div>

        {/* Live diart transcript (the transcription PROCESS runs in capture; this just displays it). */}
        {segs.length > 0 ? (
          <div className="mt-4 min-h-0 flex-1 overflow-y-auto rounded-2xl border border-border bg-background/60 p-3">
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
        ) : null}

        {error ? <p className="mt-3 text-xs text-destructive">{error}</p> : null}

        <div className="mt-5 flex items-center justify-end gap-3">
          <button
            onClick={close}
            className="rounded-full px-4 py-2 text-xs font-medium text-muted-foreground transition hover:text-foreground"
          >
            {ending ? "Close" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
