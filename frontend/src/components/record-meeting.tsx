/**
 * In-person Record — orange pill CTA + modal (Vantage language, sibling of
 * UploadTranscriptButton). Captures the room mic in-browser (getUserMedia +
 * MediaRecorder), then POSTs the clip to /api/workspaces/{id}/record where the
 * server diarizes + identifies it against the workspace's consented voiceprints
 * (FPM) and transcribes it (NEAR Whisper), merges, and ingests it. 202 →
 * navigate to /meeting/[id], which renders the processing state.
 *
 * This is Conclave ingress mode 3 (bot · upload · record).
 */
"use client";

import { Loader2, Mic, Square, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { ApiError, workspaces } from "@/lib/api";

function fmt(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
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
  const [blob, setBlob] = useState<Blob | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [intent, setIntent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopTracks = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (tickRef.current) clearInterval(tickRef.current);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setBlob(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone permission denied.");
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    const rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => {
      if (e.data.size) chunksRef.current.push(e.data);
    };
    rec.onstop = () => {
      setBlob(new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" }));
      stopTracks();
      setRecording(false);
    };
    rec.start();
    recorderRef.current = rec;
    setRecording(true);
    setSeconds(0);
    tickRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
  }, [stopTracks]);

  const stop = useCallback(() => {
    recorderRef.current?.stop();
    if (tickRef.current) clearInterval(tickRef.current);
  }, []);

  function close() {
    if (recording) stop();
    stopTracks();
    onClose();
  }

  async function handleSubmit() {
    if (!blob || busy) return;
    setBusy(true);
    setError(null);
    try {
      const ext = (blob.type.split("/")[1] || "webm").split(";")[0];
      const resp = await workspaces.recordMeeting(workspaceId, {
        blob,
        filename: `recording-${Date.now()}.${ext}`,
        intent: intent.trim() || undefined,
      });
      router.push(`/meeting/${resp.session_id}`);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 503
          ? "In-person recording isn't configured on this server yet."
          : err instanceof ApiError && err.status === 422
            ? "No speech was transcribed from that recording — try again, closer to the mic."
            : err instanceof Error
              ? err.message
              : "Recording failed",
      );
      setBusy(false);
    }
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
        className="w-full max-w-lg rounded-3xl border border-border bg-card p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold tracking-tight">
              Record an in-person meeting
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Captured in your browser, then identified and transcribed inside
              the enclave — speakers who consented are named, everyone else stays
              anonymous.
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
        <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-input bg-secondary/50 p-8 text-center">
          {!recording ? (
            <button
              onClick={start}
              disabled={busy}
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
          <p className="text-[11px] text-muted-foreground">
            {recording
              ? "Recording — tap to stop"
              : blob
                ? "Recorded. Review below or re-record."
                : "Tap the mic to start"}
          </p>
        </div>

        {blob ? (
          <audio
            controls
            src={URL.createObjectURL(blob)}
            className="mt-4 w-full"
          />
        ) : null}

        <input
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="Focus / intent (optional) — what should the notes focus on?"
          disabled={busy}
          className="mt-3 w-full rounded-xl border border-input bg-background px-3 py-2 text-xs placeholder:text-muted-foreground/60 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />

        {error ? (
          <p className="mt-3 text-xs text-destructive">{error}</p>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-3">
          <button
            onClick={close}
            disabled={busy}
            className="rounded-full px-4 py-2 text-xs font-medium text-muted-foreground transition hover:text-foreground"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={busy || !blob || recording}
            className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-2.5 text-xs font-bold text-primary-foreground shadow-lg shadow-primary/20 transition-all hover:bg-primary/90 active:scale-95 disabled:pointer-events-none disabled:opacity-50"
          >
            {busy ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Identifying…
              </>
            ) : (
              "Identify & process"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
