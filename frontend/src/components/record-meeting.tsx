/**
 * In-person Record — icon-button CTA + a small pre-flight config dialog.
 *
 * Task #14: the live capture session (mic / AudioWorklet / capture WebSocket) no
 * longer lives in this modal — it moved to the global `RecordingProvider` so a
 * recording survives navigation. This component is now just the trigger + a
 * lightweight pre-flight dialog to collect the two pre-recording settings that
 * must be locked before the stream opens:
 *   - Task #12 agenda/focus (stashed by uid → grounds the summary)
 *   - Task #30 store-audio toggle (in-person default ON)
 * On Start it calls `start()` (which creates the `inperson-…` id, stashes the
 * agenda, requests the mic + opens the WS) and navigates to `/recording/{id}` —
 * the dedicated live page. Mic-permission / WS-1008 failures surface THERE, not
 * here.
 *
 * capture diarizes live (diart) + transcribes each span and publishes
 * `[local_speaker] text`; after Stop it re-diarizes with DiariZen (authoritative)
 * + names consented speakers, then the recording page redirects to /meeting/[id].
 * This is Conclave ingress mode 3 (bot · upload · record).
 */
"use client";

import { Mic, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useRecording } from "@/components/recording-provider";
import { cn } from "@/lib/utils";

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
        aria-label="Record meeting"
        title="Record meeting"
        className={cn(
          "inline-flex size-10 items-center justify-center rounded-lg border border-border bg-card text-foreground transition-colors hover:bg-secondary",
          className,
        )}
      >
        <Mic className="size-5" aria-hidden />
      </button>
      {open ? (
        <RecordDialog workspaceId={workspaceId} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}

function RecordDialog({
  workspaceId,
  onClose,
}: {
  workspaceId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const { start } = useRecording();
  // Task #30: store the audio recording (encrypted at rest). In-person defaults ON.
  const [storeAudio, setStoreAudio] = useState(true);
  // Task #12: optional agenda/focus, locked once recording starts.
  const [agenda, setAgenda] = useState("");

  function begin() {
    const id = start(workspaceId, { agenda, storeAudio });
    onClose();
    router.push(`/recording/${id}`);
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Record meeting"
        className="flex w-full max-w-lg flex-col rounded-none border border-border bg-card p-6"
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
            onClick={onClose}
            className="flex size-8 shrink-0 items-center justify-center rounded-none bg-secondary text-muted-foreground transition hover:text-foreground"
            aria-label="Close"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Agenda / focus (Task #12) — optional; grounds the summary. */}
        <div>
          <label
            htmlFor="record-agenda"
            className="mb-1.5 block text-xs font-medium text-foreground"
          >
            Agenda or focus{" "}
            <span className="font-normal text-muted-foreground">— optional</span>
          </label>
          <textarea
            id="record-agenda"
            value={agenda}
            onChange={(e) => setAgenda(e.target.value)}
            rows={2}
            placeholder="What's this meeting about? e.g. decide Q3 pricing; focus on the launch date."
            className="w-full resize-none rounded-none border border-border bg-background/60 px-4 py-3 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
          />
          <p className="mt-1 text-[11px] text-muted-foreground">
            Steers the summary and insights toward what matters to you.
          </p>
        </div>

        {/* Store-audio toggle (Task #30) — in-person default ON. */}
        <label className="mt-4 flex items-center gap-3 rounded-none border border-border bg-background/60 px-4 py-3">
          <input
            type="checkbox"
            checked={storeAudio}
            onChange={(e) => setStoreAudio(e.target.checked)}
            className="size-4 accent-primary"
          />
          <span className="text-xs text-foreground">
            Store the audio recording
            <span className="ml-1 text-muted-foreground">
              — encrypted in the enclave, replayable later. Off = transcript only, no audio kept.
            </span>
          </span>
        </label>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="rounded-none px-4 py-2 text-xs font-medium text-muted-foreground transition hover:text-foreground"
          >
            Cancel
          </button>
          <button
            onClick={begin}
            className="inline-flex items-center gap-2 rounded-none bg-primary px-5 py-2.5 text-xs font-bold text-primary-foreground transition hover:bg-primary/90 active:scale-95"
          >
            <Mic className="size-4" aria-hidden />
            Start recording
          </button>
        </div>
      </div>
    </div>
  );
}
