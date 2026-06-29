"use client";

import { useState } from "react";

import { shapeContrib } from "@/lib/api";

/**
 * Task #20 — host-triggered "Contribute to Shape Rotator OS" button.
 *
 * Enabled ONLY after the host approves the v2 transcript (`approved`), so the
 * contribution is built from the corrected transcript, not raw ASR. Click opens
 * an inline confirm panel (the consent / opt-in). Confirm → POST
 * /api/meetings/{id}/contribute-shapeos (Arm 1: approved v2 → Shape OS's
 * `context_submissions` inbox) → "Posted to inbox ✓". Nothing fires automatically.
 */
export function ContributeShapeOS({
  sessionId,
  approved,
}: {
  sessionId: string;
  approved: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ parts: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function contribute() {
    setBusy(true);
    setErr(null);
    try {
      const res = await shapeContrib.contribute(sessionId);
      if (res.inbox.ok) {
        setDone({ parts: res.inbox.parts });
        setConfirming(false);
      } else {
        setErr(errorFor(res.inbox.status));
      }
    } catch {
      setErr("Couldn't reach Shape Rotator OS. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <p
        data-testid="shapeos-posted"
        className="mt-4 inline-flex items-center gap-2 text-xs font-semibold text-attested"
      >
        <span className="size-1.5 rounded-full bg-attested" />
        Posted to Shape Rotator OS inbox ✓
        {done.parts > 1 ? <span className="text-muted-foreground">({done.parts} parts)</span> : null}
      </p>
    );
  }

  return (
    <div className="mt-6 border-t border-border pt-4">
      {!confirming ? (
        <button
          data-testid="contribute-shapeos-btn"
          disabled={!approved}
          title={
            approved
              ? "Send this meeting's approved transcript to the Shape Rotator OS cohort inbox"
              : "Approve the transcript first"
          }
          onClick={() => {
            setErr(null);
            setConfirming(true);
          }}
          className="rounded border border-border px-4 py-1.5 text-sm font-semibold transition-colors hover:border-foreground hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-40"
        >
          Contribute to Shape Rotator OS
        </button>
      ) : (
        <div
          data-testid="contribute-shapeos-confirm"
          className="rounded-xl border border-border bg-card p-4"
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-foreground">
            Share with the Shape Rotator OS cohort?
          </p>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            This sends the <strong>approved</strong> transcript of this meeting to the cohort&apos;s
            Shape Rotator OS context inbox. Only do this for a meeting you own and whose participants
            consented to share.
          </p>
          <div className="mt-3 flex items-center gap-2">
            <button
              data-testid="contribute-shapeos-confirm-btn"
              disabled={busy}
              onClick={contribute}
              className="rounded bg-foreground px-4 py-1.5 text-sm font-semibold text-background disabled:opacity-40"
            >
              {busy ? "Posting…" : "Yes, contribute"}
            </button>
            <button
              disabled={busy}
              onClick={() => setConfirming(false)}
              className="rounded border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-40"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
      {err ? <p className="mt-2 text-xs text-destructive">{err}</p> : null}
    </div>
  );
}

function errorFor(status: string): string {
  switch (status) {
    case "unconfigured":
      return "Shape Rotator OS contribution isn't configured on this server.";
    case "forbidden":
      return "Shape Rotator OS rejected the request (auth).";
    case "rejected":
      return "Shape Rotator OS rejected the transcript (validation).";
    default:
      return "Couldn't reach Shape Rotator OS. Try again.";
  }
}
