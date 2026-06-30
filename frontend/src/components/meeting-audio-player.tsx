/**
 * Meeting-page audio player (Task #30).
 *
 * Streams the full meeting recording from the decrypt-on-read endpoint
 * (`/api/transcripts/sessions/{id}/audio`). Cookie auth is same-origin, so the
 * URL is used directly as an <audio src> — the backend decrypts in memory and
 * never writes plaintext back to disk.
 *
 * Self-hiding: renders nothing when the meeting explicitly opted out of storing
 * audio (`storeAudio === false`), after the owner deletes it, or when the fetch
 * 404s (no audio / legacy session) via the <audio> onError. The owner gets a
 * "Delete audio" control (transcript + insights are untouched).
 */
"use client";

import { useState } from "react";

import { meetings as meetingsApi } from "@/lib/api";

export function MeetingAudioPlayer({
  sessionId,
  isOwner = false,
  storeAudio,
}: {
  sessionId: string;
  isOwner?: boolean;
  storeAudio?: boolean | null;
}) {
  const [gone, setGone] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (storeAudio === false || gone) return null;

  const onDelete = async () => {
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
  };

  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-wide text-muted-foreground">
          Recording
        </h3>
        {isOwner ? (
          <button
            type="button"
            onClick={onDelete}
            disabled={deleting}
            className="text-[0.7rem] font-medium text-destructive transition hover:opacity-80 disabled:opacity-50"
          >
            {deleting ? "Deleting…" : "Delete audio"}
          </button>
        ) : null}
      </div>
      <audio
        controls
        preload="metadata"
        src={meetingsApi.audioUrl(sessionId)}
        onError={() => setGone(true)}
        className="mt-3 w-full"
      >
        Your browser does not support audio playback.
      </audio>
    </div>
  );
}
