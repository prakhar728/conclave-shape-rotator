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

// Deliberate-abort WebSocket close code (application range 3000-4999). Capture
// skips finalize (no upload / no meeting-completed webhook / no post-pass) when
// a stream closes with this code, so a CANCELED recording never enters the
// transcription pipeline. A plain disconnect (1006/1001) still finalizes.
const CANCEL_CLOSE_CODE = 4001;

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
  /**
   * Live mic amplitude for the recording visualizer: `bars` normalized (0..1)
   * frequency-band levels read from an AnalyserNode on the live stream, or null
   * when this tab isn't holding the mic (not recording / SSE-only view). Reads a
   * ref imperatively — safe to poll on an interval without re-rendering.
   */
  getAudioLevels: (bars: number) => number[] | null;
};

const RecordingContext = createContext<RecordingContextValue | null>(null);

export function RecordingProvider({ children }: { children: React.ReactNode }) {
  const [recording, setRecording] = useState<ActiveRecording | null>(null);

  const ctxRef = useRef<AudioContext | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sockRef = useRef<WebSocket | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // The id of the CURRENT session; async setup checks it against its own id so a
  // cancel mid-mic-request aborts + tears down instead of leaking the stream.
  const idRef = useRef<string>("");
  // Fallback timer so a recording can't hang in "ending" forever if `done` never arrives.
  const endTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopTick = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }, []);

  const clearEndTimer = useCallback(() => {
    if (endTimerRef.current) {
      clearTimeout(endTimerRef.current);
      endTimerRef.current = null;
    }
  }, []);

  // Release the MIC + audio pipeline (hardware capture) — but NOT the WebSocket.
  // Called the instant Stop is pressed so macOS stops showing "recording" while
  // the finalize `done` is still in flight over the (still-open) socket.
  const releaseCapture = useCallback(() => {
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
    nodeRef.current = null;
    analyserRef.current = null;
    ctxRef.current = null;
    streamRef.current = null;
  }, [stopTick]);

  const teardown = useCallback(() => {
    releaseCapture();
    clearEndTimer();
    try {
      const s = sockRef.current;
      if (s && (s.readyState === 0 || s.readyState === 1)) s.close();
    } catch {}
    sockRef.current = null;
  }, [releaseCapture, clearEndTimer]);

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
      // Task #32: stash the recorder identity (always, even with no agenda) so the
      // finalize webhook uses the actual recorder as the VFTE identify host. The
      // server derives WHO from the session cookie; we only send the meeting uid.
      try {
        await workspaces.recordRecorder(workspaceId, { uid: id });
      } catch {
        /* non-fatal: identify falls back to the workspace owner */
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
        const source = ctx.createMediaStreamSource(stream);
        source.connect(node);
        node.connect(sink).connect(ctx.destination);
        // Tap the same source for the live visualizer. The analyser is a passive
        // sink (no onward connection needed) — it never touches the PCM sent to
        // capture, it just lets the page poll real amplitude.
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 128; // 64 frequency bins
        analyser.smoothingTimeConstant = 0.7;
        source.connect(analyser);
        analyserRef.current = analyser;

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
      setRecording((r) => (r ? { ...r, status: "ending" } : r));
      try {
        sock.send(new ArrayBuffer(0)); // empty frame = meeting-end (capture uploads + fires the webhook)
      } catch {}
      // Release the mic + audio pipeline NOW — there are no more frames to send.
      // The WS stays open only to receive the finalize `done`. This stops macOS
      // showing "recording" the moment Stop is pressed, even if `done` is slow.
      releaseCapture();
      // Safety net: if `done` never arrives, don't hang in "ending" forever.
      clearEndTimer();
      const sid = idRef.current;
      endTimerRef.current = setTimeout(() => {
        teardown();
        setRecording((r) => (r && r.id === sid ? { ...r, status: "done" } : r));
      }, 120000);
    } else {
      teardown();
      idRef.current = "";
      setRecording(null);
    }
  }, [teardown, releaseCapture, clearEndTimer]);

  const cancel = useCallback(() => {
    // Abort, do NOT finalize. Unlike stop(), cancel must never push the recording
    // into the pipeline, so we do NOT send the empty end-frame (stop's meeting-end
    // signal). We close with CANCEL_CLOSE_CODE because a plain close ALSO finalizes
    // on the capture side (its WebSocketDisconnect handler uploads + notifies).
    const sock = sockRef.current;
    try {
      if (sock && (sock.readyState === 0 || sock.readyState === 1)) {
        sock.close(CANCEL_CLOSE_CODE, "canceled");
      }
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

  const getAudioLevels = useCallback((bars: number): number[] | null => {
    const analyser = analyserRef.current;
    if (!analyser || bars <= 0) return null;
    const bins = analyser.frequencyBinCount;
    const data = new Uint8Array(bins);
    analyser.getByteFrequencyData(data);
    const per = Math.max(1, Math.floor(bins / bars));
    const out: number[] = [];
    for (let i = 0; i < bars; i++) {
      let sum = 0;
      for (let j = 0; j < per; j++) sum += data[i * per + j] ?? 0;
      out.push(sum / per / 255); // 0..1
    }
    return out;
  }, []);

  // Tear the session down if the provider itself unmounts (mounted once at the
  // root in practice, but this clears the ticker/mic/WS in tests + on HMR).
  useEffect(() => teardown, [teardown]);

  const value = useMemo<RecordingContextValue>(
    () => ({ recording, start, stop, cancel, clear, getAudioLevels }),
    [recording, start, stop, cancel, clear, getAudioLevels],
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
