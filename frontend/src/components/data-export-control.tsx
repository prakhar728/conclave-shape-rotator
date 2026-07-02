/**
 * Settings section: "Download my data" (Task #18).
 *
 * Exports the signed-in user's OWN meetings (transcripts, summaries + signals,
 * shares, KB knowledge, voiceprint refs) as a ZIP. Audio is opt-in:
 *   - OFF (default) → a synchronous download (browser navigation).
 *   - ON            → an async build on the #16 queue (audio is large / must be
 *     decrypted); we poll the job, then trigger the download when it's ready.
 */
"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { dataExport } from "@/lib/api";

export function DataExportControl() {
  const [includeAudio, setIncludeAudio] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function triggerDownload(url: string) {
    // Same-origin navigation carries the session cookie; the browser saves the ZIP.
    const a = document.createElement("a");
    a.href = url;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function handleExport() {
    setError(null);
    setStatus(null);

    if (!includeAudio) {
      // Synchronous path — no audio, no queue.
      triggerDownload(dataExport.downloadUrl());
      setStatus("Your download should begin shortly.");
      return;
    }

    // Async path — build with audio on the queue, then poll for completion.
    setBusy(true);
    setStatus("Preparing your export (including audio)…");
    try {
      const job = await dataExport.startJob(true);
      pollRef.current = setInterval(async () => {
        try {
          const s = await dataExport.jobStatus(job.export_id);
          if (s.status === "done") {
            if (pollRef.current) clearInterval(pollRef.current);
            setBusy(false);
            setStatus("Export ready — downloading…");
            triggerDownload(dataExport.jobDownloadUrl(job.export_id));
          } else if (s.status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            setBusy(false);
            setError(s.error || "Export failed. Please try again.");
          }
        } catch {
          // transient poll error — keep polling
        }
      }, 2000);
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : "Could not start export");
    }
  }

  return (
    <section className="mt-8 rounded-none border border-border bg-card p-5">
      <h2 className="text-sm font-medium">Download my data</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Export a ZIP of everything Conclave holds for the meetings you own —
        transcripts, summaries and derived signals, sharing settings, and
        knowledge-graph entities. Voiceprints are referenced by id only; download
        the actual voiceprints from your fingerprint dashboard.
      </p>

      <label className="mt-4 flex items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          checked={includeAudio}
          onChange={(e) => setIncludeAudio(e.target.checked)}
          disabled={busy}
          className="h-4 w-4 rounded-none border-border"
        />
        Include audio recordings (larger; prepared in the background)
      </label>

      <div className="mt-4 flex items-center gap-3">
        <Button onClick={handleExport} disabled={busy}>
          {busy ? "Preparing…" : "Download my data"}
        </Button>
        {status ? (
          <span className="text-xs text-muted-foreground">{status}</span>
        ) : null}
        {error ? <span className="text-xs text-destructive">{error}</span> : null}
      </div>
    </section>
  );
}
