"use client";

import { useState } from "react";

import { refine, type V2Draft } from "@/lib/api";

/**
 * Footer actions for the refine editor: a passive "insights are stale" badge
 * (#5 — they re-derive on approve, not per edit) + the Approve & build button.
 */
export function RefineActions({
  draft,
  sessionId,
  onApproved,
}: {
  draft: V2Draft;
  sessionId: string;
  onApproved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const approved = draft.status === "approved";

  async function approve() {
    setBusy(true);
    setErr(null);
    try {
      await refine.approve(sessionId);
      onApproved();
    } catch {
      setErr("Couldn't approve. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 flex items-center justify-between border-t border-border pt-4">
      {draft.insights_stale ? (
        <span
          data-testid="stale-badge"
          className="inline-flex items-center gap-1 rounded-none border border-border px-2 py-0.5 text-xs text-muted-foreground"
        >
          ⟳ Insights update when you approve
        </span>
      ) : (
        <span />
      )}
      <div className="flex items-center gap-2">
        {err ? <span className="text-xs text-destructive">{err}</span> : null}
        <button
          data-testid="approve-btn"
          disabled={busy || approved}
          onClick={approve}
          className="rounded-none bg-foreground px-4 py-1.5 text-sm font-semibold text-background disabled:opacity-40"
        >
          {approved ? "Approved" : busy ? "Approving…" : "Approve & build"}
        </button>
      </div>
    </div>
  );
}
