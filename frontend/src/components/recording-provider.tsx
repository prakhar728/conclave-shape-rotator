/**
 * Global recording session provider (Task #14).
 *
 * The in-person live-capture session — mic `MediaStream`, `AudioContext` +
 * `AudioWorkletNode` PCM emitter, and the capture `WebSocket` — used to live
 * inside the `RecordModal` overlay, so it died the moment you navigated or
 * dismissed the modal. It now lives HERE, mounted once in `layout.tsx` above the
 * router, so a recording SURVIVES navigation: the `/recording/[id]` page is just
 * a *view* onto this shared session, and `AppShell` shows a "still recording"
 * indicator while you move around.
 *
 * The trigger (`RecordMeetingButton`) calls `start()` (which creates the
 * `inperson-…` id, stashes the agenda, requests the mic, opens the WS) and then
 * navigates to `/recording/{id}`. Segments arrive over the WS exactly as before;
 * the page also reads the backend SSE (`/api/meetings/{id}/live`) as a second,
 * refresh-survivable source when it does NOT own the live WS.
 *
 * Transport/teardown care: `cancel()` (abandon) sends the empty end-frame and
 * fully tears down mic + WS + AudioContext + ticker (no leaks); a mic-permission
 * failure or a WS 1008 reject surfaces as `recording.error` for the page to show
 * inline. A hard browser reload unavoidably resets this state — the page then
 * falls back to the SSE view.
 */
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { workspaces } from "@/lib/api";

// capture's in-person WebSocket base (e.g. ws://localhost:8087) + the engine token. Public env so the
// browser can reach capture directly; in production this is capture's edge URL + a per-session token.
const CAPTURE_WS_BASE =
  process.env.NEXT_PUBLIC_CAPTURE_INPERSON_WS_URL || "ws://localhost:8087";
const CAPTURE_TOKEN =
  process.env.NEXT_PUBLIC_CAPTURE_DIARIZE_TOKEN || "dev-diarize-token";

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

export type LiveSeg = { start: number; end: number; speaker: string; text?: string };

/** mm:ss elapsed formatter (shared with the page + the AppShell indicator). */
export function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function newMeetingId(): string {
  const rand = Math.random().toString(36).slice(2, 8);
  return `inperson-${Date.now()}-${rand}`;
}

export type RecordingStatus =
  | "starting" // mic requested / WS connecting
  | "recording" // WS open, streaming
  | "ending" // Stop pressed, empty frame sent, awaiting finalize `done`
  | "done" // capture finished upload + fired the webhook → page redirects
  | "error"; // mic denied / WS 1008 / connection dropped

export type ActiveRecording = {
  id: string;
  workspaceId: string;
  status: RecordingStatus;
  seconds: number;
  segs: LiveSeg[];
  error: string | null;
  storeAudio: boolean;
};

type RecordingContextValue = {
  /** The one in-flight (or just-finished) recording, or null. */
  recording: ActiveRecording | null;
  /** Create the id, stash the agenda, request mic + open WS; returns the new id. */
  start: (
    workspaceId: string,
    opts: { agenda?: string; storeAudio: boolean },
  ) => string;
  /** Stop: send the empty end-frame, enter "ending"; keep the WS open for `done`. */
  stop: () => void;
  /** Abandon: send the end-frame if open, then fully tear down (no leaks) + clear. */
  cancel: () => void;
  /** Drop the finished session (called by the page after the `done` redirect). */
  clear: () => void;
};

const RecordingContext = createContext<RecordingContextValue | null>(null);

export function RecordingProvider({ children }: { children: React.ReactNode }) {
  const [recording, setRecording] = useState<ActiveRecording | null>(null);

  const ctxRef = useRef<AudioContext | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sockRef = useRef<WebSocket | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // The id of the CURRENT session; async setup checks it against its own id so a
  // cancel mid-mic-request aborts + tears down instead of leaking the stream.
  const idRef = useRef<string>("");

  const stopTick = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  const teardown = useCallback(() => {
    try {
      nodeRef.current?.disconnect();
    } catch {}
    try {
      ctxRef.current?.close();
    } catch {}
    try {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    } catch {}
    stopTick();
    try {
      const s = sockRef.current;
      if (s && (s.readyState === 0 || s.readyState === 1)) s.close();
    } catch {}
    nodeRef.current = null;
    ctxRef.current = null;
    streamRef.current = null;
    sockRef.current = null;
  }, [stopTick]);

  const begin = useCallback(
    async (
      id: string,
      workspaceId: string,
      agenda: string,
      storeAudio: boolean,
    ) => {
      // Task #12: stash the agenda BEFORE the stream starts so it's persisted by
      // the time the finalize webhook fires. Best-effort — a stash failure must
      // not block the recording (the meeting just runs ungrounded, prior behavior).
      if (agenda.trim()) {
        try {
          await workspaces.recordAgenda(workspaceId, { uid: id, agenda: agenda.trim() });
        } catch {
          /* non-fatal: proceed without agenda grounding */
        }
      }
      if (idRef.current !== id) return; // cancelled while stashing

      const url =
        `${CAPTURE_WS_BASE.replace(/\/$/, "")}/v1/inperson/stream` +
        `?uid=${encodeURIComponent(id)}&workspace=${encodeURIComponent(workspaceId)}` +
        `&token=${encodeURIComponent(CAPTURE_TOKEN)}` +
        `&store_audio=${storeAudio ? "true" : "false"}`;

      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1 },
        });
        if (idRef.current !== id) {
          // Cancelled while the permission prompt was up — don't leak the mic.
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;

        const ctx = new AudioContext({ sampleRate: 16000 });
        ctxRef.current = ctx;
        await ctx.audioWorklet.addModule(
          URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" })),
        );
        if (idRef.current !== id) {
          teardown();
          return;
        }
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
          tickRef.current = setInterval(() => {
            setRecording((r) =>
              r && r.id === id ? { ...r, seconds: r.seconds + 1 } : r,
            );
          }, 1000);
          setRecording((r) =>
            r && r.id === id ? { ...r, status: "recording" } : r,
          );
        };
        sock.onmessage = (e) => {
          const m = JSON.parse(e.data as string);
          if (m.type === "done") {
            // capture uploaded the recording + fired the finalize webhook → safe
            // to hand off. Tear down transport; the page redirects to /meeting/[id].
            teardown();
            setRecording((r) => (r && r.id === id ? { ...r, status: "done" } : r));
            return;
          }
          setRecording((r) =>
            r && r.id === id ? { ...r, segs: [...r.segs, m as LiveSeg] } : r,
          );
        };
        sock.onerror = () => {
          setRecording((r) =>
            r && r.id === id
              ? {
                  ...r,
                  error:
                    "Connection to the capture service failed (token / service up?).",
                }
              : r,
          );
        };
        sock.onclose = (ev) => {
          stopTick();
          setRecording((r) => {
            if (!r || r.id !== id) return r;
            if (r.status === "ending" || r.status === "done") return r; // expected
            if (ev.code === 1008) {
              return {
                ...r,
                status: "error",
                error: "Rejected — bad or missing capture token.",
              };
            }
            if (r.status === "error") return r;
            return {
              ...r,
              status: "error",
              error: r.error ?? "Recording connection closed.",
            };
          });
        };
      } catch (err) {
        teardown();
        setRecording((r) =>
          r && r.id === id
            ? {
                ...r,
                status: "error",
                error:
                  err instanceof Error ? err.message : "Could not start recording",
              }
            : r,
        );
      }
    },
    [teardown, stopTick],
  );

  const start = useCallback(
    (workspaceId: string, opts: { agenda?: string; storeAudio: boolean }) => {
      // A fresh session supersedes any previous one — tear the old one down first.
      teardown();
      const id = newMeetingId();
      idRef.current = id;
      setRecording({
        id,
        workspaceId,
        status: "starting",
        seconds: 0,
        segs: [],
        error: null,
        storeAudio: opts.storeAudio,
      });
      void begin(id, workspaceId, opts.agenda ?? "", opts.storeAudio);
      return id;
    },
    [begin, teardown],
  );

  const stop = useCallback(() => {
    const sock = sockRef.current;
    if (sock && sock.readyState === 1) {
      stopTick();
      setRecording((r) => (r ? { ...r, status: "ending" } : r));
      sock.send(new ArrayBuffer(0)); // empty frame = meeting-end (capture uploads + fires the webhook)
    } else {
      teardown();
      idRef.current = "";
      setRecording(null);
    }
  }, [teardown, stopTick]);

  const cancel = useCallback(() => {
    const sock = sockRef.current;
    try {
      if (sock && sock.readyState === 1) sock.send(new ArrayBuffer(0));
    } catch {}
    teardown();
    idRef.current = "";
    setRecording(null);
  }, [teardown]);

  const clear = useCallback(() => {
    teardown();
    idRef.current = "";
    setRecording(null);
  }, [teardown]);

  // Tear the session down if the provider itself unmounts (mounted once at the
  // root in practice, but this clears the ticker/mic/WS in tests + on HMR).
  useEffect(() => teardown, [teardown]);

  const value = useMemo<RecordingContextValue>(
    () => ({ recording, start, stop, cancel, clear }),
    [recording, start, stop, cancel, clear],
  );

  return (
    <RecordingContext.Provider value={value}>
      {children}
    </RecordingContext.Provider>
  );
}

export function useRecording(): RecordingContextValue {
  const ctx = useContext(RecordingContext);
  if (!ctx) {
    throw new Error("useRecording must be used inside <RecordingProvider>");
  }
  return ctx;
}
