/**
 * Speaker tag form — name + email → VFTE voiceprint→identity binding (consent plane).
 *
 * Extracted from transcript-panel.tsx so the read-only meeting transcript AND the
 * refine editor host the EXACT same tagging affordance (the editor is slated to
 * replace that page — Task #9/#13). The caller owns the tagSpeaker call + the
 * pending/confirmed state; this is just the form.
 */
"use client";

import { useState } from "react";

export function SpeakerTagForm({
  label,
  busy,
  err,
  initialName = "",
  onCancel,
  onSubmit,
}: {
  label: string;
  busy: boolean;
  err: string | null;
  // Task #3 — pre-fill the name (the "Proposed:" Confirm/Edit path). The host
  // still fills in the email, so a proposal is only created on submit.
  initialName?: string;
  onCancel: () => void;
  onSubmit: (label: string, name: string, email: string) => void;
}) {
  const [name, setName] = useState(initialName);
  const [email, setEmail] = useState("");
  const ready = name.trim() !== "" && email.trim() !== "";
  return (
    <div
      data-testid="speaker-tag-form"
      className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-border p-2"
    >
      <span className="text-[0.7rem] uppercase tracking-wide text-muted-foreground">
        Who is {label}?
      </span>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Full name"
        className="rounded border border-border bg-background px-2 py-1 text-xs"
      />
      <input
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="email@company.com"
        className="rounded border border-border bg-background px-2 py-1 text-xs"
      />
      <button
        type="button"
        disabled={!ready || busy}
        onClick={() => onSubmit(label, name.trim(), email.trim())}
        className="rounded bg-foreground px-3 py-1 text-xs font-semibold text-background disabled:opacity-40"
      >
        {busy ? "Tagging…" : "Tag"}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="rounded border border-border px-3 py-1 text-xs"
      >
        Cancel
      </button>
      {err ? <span className="text-[0.7rem] text-destructive">{err}</span> : null}
    </div>
  );
}
