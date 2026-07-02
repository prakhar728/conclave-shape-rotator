/**
 * The meeting-page heading (Task #40): shows the meeting title (owner rename or
 * the LLM-generated one; legacy → summary first line) and, for the owner, a quiet
 * inline rename affordance. Saving PATCHes `…/title`; a blank value clears the
 * override and reverts to the auto title.
 */
"use client";

import { Check, Pencil, X } from "lucide-react";
import { useState } from "react";

import { meetings as meetingsApi } from "@/lib/api";
import { meetingTitle } from "@/lib/meetingTitle";

export function MeetingTitleHeading({
  sessionId,
  title,
  summary,
  isOwner,
  onRenamed,
}: {
  sessionId: string;
  title?: string | null;
  summary?: string | null;
  isOwner: boolean;
  onRenamed?: (title: string | null) => void;
}) {
  const heading = meetingTitle(title, summary);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function open() {
    // Seed with the current explicit title (not the summary fallback) so an
    // empty field means "clear the override".
    setValue((title ?? "").trim());
    setError(null);
    setEditing(true);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const res = await meetingsApi.rename(sessionId, value);
      onRenamed?.(res.title);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Rename failed");
    } finally {
      setSaving(false);
    }
  }

  if (editing) {
    return (
      <div className="mt-4 flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <input
            autoFocus
            data-testid="title-input"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void save();
              if (e.key === "Escape") setEditing(false);
            }}
            placeholder="Meeting title (blank = auto)"
            className="w-full max-w-xl rounded-md border border-border bg-background px-2 py-1 font-heading text-2xl font-bold tracking-tight text-foreground md:text-3xl"
          />
          <button
            type="button"
            aria-label="Save title"
            data-testid="title-save"
            onClick={() => void save()}
            disabled={saving}
            className="shrink-0 text-muted-foreground transition hover:text-foreground disabled:opacity-50"
          >
            <Check className="size-5" />
          </button>
          <button
            type="button"
            aria-label="Cancel rename"
            onClick={() => setEditing(false)}
            disabled={saving}
            className="shrink-0 text-muted-foreground transition hover:text-foreground disabled:opacity-50"
          >
            <X className="size-5" />
          </button>
        </div>
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
      </div>
    );
  }

  return (
    <div className="mt-4 flex items-start gap-2">
      <h1
        data-testid="meeting-title"
        className="font-heading text-2xl font-bold tracking-tight text-foreground md:text-3xl"
      >
        {heading}
      </h1>
      {isOwner ? (
        <button
          type="button"
          aria-label="Rename meeting"
          data-testid="title-edit"
          onClick={open}
          className="mt-1 shrink-0 text-muted-foreground/50 transition hover:text-foreground"
        >
          <Pencil className="size-4" />
        </button>
      ) : null}
    </div>
  );
}
