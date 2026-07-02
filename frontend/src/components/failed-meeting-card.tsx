/**
 * Task #42 — a dashboard card for a meeting whose enrichment failed / never
 * produced insights (a cancelled recording, an empty transcript, or an LLM
 * error). Instead of an eternal "Sharpening insights…" spinner, the owner gets
 * a "couldn't generate insights" state with Retry + Delete.
 */
"use client";

import { AlertTriangle, Trash2 } from "lucide-react";
import { useState } from "react";

import { useConfirm } from "@/components/confirm-dialog";
import { meetings as meetingsApi, type Meeting } from "@/lib/api";

export function FailedMeetingCard({
  meeting,
  onChanged,
}: {
  meeting: Meeting;
  onChanged: () => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const { confirm, dialog } = useConfirm();

  async function retry() {
    setBusy(true);
    try {
      await meetingsApi.retryEnrich(meeting.session_id);
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  async function del() {
    const ok = await confirm({
      title: "Delete this meeting?",
      body: "This can't be undone.",
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await meetingsApi.delete(meeting.session_id);
      await onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="failed-card"
      className="rounded-xl border border-border bg-card p-6"
    >
      {dialog}
      <div className="flex items-center gap-3">
        <AlertTriangle className="size-4 shrink-0 text-signal-warn" aria-hidden />
        <p className="text-sm font-medium text-foreground">
          Couldn&rsquo;t generate insights
        </p>
      </div>
      <p className="mt-2 font-mono text-[10px] text-muted-foreground">
        {meeting.date} · {meeting.source} · {meeting.session_id}
      </p>
      <p className="mt-2 text-xs text-muted-foreground">
        This meeting didn&rsquo;t produce a summary — the recording may have been
        empty or enrichment failed. Retry, or delete it.
      </p>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          data-testid="failed-retry"
          onClick={retry}
          disabled={busy}
          className="rounded-md border border-border px-3 py-1 text-xs font-medium transition hover:bg-secondary disabled:opacity-50"
        >
          Retry
        </button>
        <button
          type="button"
          data-testid="failed-delete"
          onClick={del}
          disabled={busy}
          className="inline-flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium text-muted-foreground transition hover:text-destructive disabled:opacity-50"
        >
          <Trash2 className="size-3.5" aria-hidden />
          Delete
        </button>
      </div>
    </div>
  );
}
