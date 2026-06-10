/**
 * Owner-only controls on the meeting detail page.
 *
 * Two affordances (Phase 2.12, 2.13):
 *  - Visibility toggle: owner-only ⇄ shared
 *  - Attendee list + add-by-email form
 *
 * Mounting condition is the caller's job: only render when MeetingView.is_owner
 * is true. We don't double-gate here.
 */
"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  meetingOwner,
  type MeetingShare,
  type ShareScope,
} from "@/lib/api";

type Visibility = "owner-only" | "shared";

const SCOPE_LABELS: Record<ShareScope, string> = {
  summary_and_transcript: "Summary + transcript",
  summary_only: "Summary only",
};

export function OwnerControls({
  sessionId,
  initialVisibility,
}: {
  sessionId: string;
  initialVisibility: Visibility;
}) {
  const [visibility, setVisibility] = useState<Visibility>(initialVisibility);
  const [shares, setShares] = useState<MeetingShare[] | null>(null);
  const [email, setEmail] = useState("");
  const [scope, setScope] = useState<ShareScope>("summary_and_transcript");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    meetingOwner
      .listShares(sessionId)
      .then((r) => {
        if (!cancelled) setShares(r.shares);
      })
      .catch(() => {
        if (!cancelled) setShares([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  async function toggleVisibility() {
    const next: Visibility = visibility === "shared" ? "owner-only" : "shared";
    setBusy(true);
    setError(null);
    try {
      await meetingOwner.setVisibility(sessionId, next);
      setVisibility(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddShare(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await meetingOwner.addShare(sessionId, email.trim(), scope);
      const added: MeetingShare = {
        email: r.email,
        granted_at: new Date().toISOString(),
        scope: r.scope,
      };
      // Re-sharing the same email updates its scope rather than duplicating.
      setShares((prev) => {
        const rest = (prev ?? []).filter((s) => s.email !== added.email);
        return [...rest, added];
      });
      setEmail("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        setError("Enter a valid email address.");
      } else {
        setError(e instanceof Error ? e.message : "Failed to add");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-8 rounded-lg border border-border bg-card p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium">Sharing</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {visibility === "owner-only"
              ? "Only you can see this meeting."
              : `Visible to you and ${shares?.length ?? "the people"} you've added below.`}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={toggleVisibility}
          disabled={busy}
        >
          {visibility === "shared" ? "Make private" : "Share"}
        </Button>
      </div>

      {visibility === "shared" ? (
        <>
          <form onSubmit={handleAddShare} className="mt-4 flex flex-wrap gap-2">
            <Input
              type="email"
              placeholder="attendee@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={busy}
              className="min-w-[12rem] flex-1"
            />
            <select
              value={scope}
              onChange={(e) => setScope(e.target.value as ShareScope)}
              disabled={busy}
              aria-label="Share permission level"
              className="h-9 rounded-md border border-border bg-background px-2 text-xs text-foreground"
            >
              <option value="summary_and_transcript">
                {SCOPE_LABELS.summary_and_transcript}
              </option>
              <option value="summary_only">{SCOPE_LABELS.summary_only}</option>
            </select>
            <Button type="submit" disabled={busy || !email.trim()}>
              Add
            </Button>
          </form>

          {shares && shares.length > 0 ? (
            <ul className="mt-4 flex flex-col gap-1">
              {shares.map((s) => (
                <li
                  key={s.email}
                  className="flex items-center justify-between gap-3 text-xs"
                >
                  <span className="text-foreground">{s.email}</span>
                  <span className="flex items-center gap-2 text-muted-foreground">
                    <span className="rounded bg-muted px-1.5 py-0.5">
                      {SCOPE_LABELS[s.scope] ?? s.scope}
                    </span>
                    {s.granted_at.split("T")[0]}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-xs text-muted-foreground">
              No one added yet. Adds before the next enrichment run will
              receive a magic link.
            </p>
          )}
        </>
      ) : null}

      {error ? <p className="mt-3 text-xs text-destructive">{error}</p> : null}
    </section>
  );
}
