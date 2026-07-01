/**
 * Owner-only controls on the meeting detail page.
 *
 * Two affordances (Phase 2.12, 2.13; Task #31):
 *  - Visibility toggle: owner-only ⇄ shared
 *  - Attendee list + add-by-email form with three independent artifact
 *    checkboxes {transcript, insights, audio} — a recipient can be granted any
 *    subset. Each row shows which artifacts that recipient can see.
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
  type ShareConfig,
} from "@/lib/api";

type Visibility = "owner-only" | "shared";

const ARTIFACTS: { key: keyof ShareConfig; label: string }[] = [
  { key: "insights", label: "Insights" },
  { key: "transcript", label: "Transcript" },
  { key: "audio", label: "Audio" },
];

const DEFAULT_CONFIG: ShareConfig = {
  transcript: true,
  insights: true,
  audio: false,
};

function sharedArtifacts(s: MeetingShare): string[] {
  return ARTIFACTS.filter((a) => s[a.key]).map((a) => a.label);
}

export function OwnerControls({
  sessionId,
  initialVisibility,
  initialSharedToWorkspace = false,
  initialOwnerOnly = false,
}: {
  sessionId: string;
  initialVisibility: Visibility;
  // Task #32 — whole-workspace share + confidential lock state.
  initialSharedToWorkspace?: boolean;
  initialOwnerOnly?: boolean;
}) {
  const [visibility, setVisibility] = useState<Visibility>(initialVisibility);
  const [shares, setShares] = useState<MeetingShare[] | null>(null);
  const [email, setEmail] = useState("");
  const [config, setConfig] = useState<ShareConfig>(DEFAULT_CONFIG);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sharedToWorkspace, setSharedToWorkspace] = useState(initialSharedToWorkspace);
  const [ownerOnly, setOwnerOnly] = useState(initialOwnerOnly);

  async function toggleWorkspaceShare() {
    setBusy(true);
    setError(null);
    try {
      const r = await meetingOwner.shareWorkspace(sessionId, !sharedToWorkspace);
      setSharedToWorkspace(r.shared_to_workspace);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setBusy(false);
    }
  }

  async function toggleOwnerOnly() {
    setBusy(true);
    setError(null);
    try {
      const r = await meetingOwner.setOwnerOnly(sessionId, !ownerOnly);
      setOwnerOnly(r.owner_only);
      if (r.owner_only) setSharedToWorkspace(false); // locking revokes the ws share
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setBusy(false);
    }
  }

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
    if (!config.transcript && !config.insights && !config.audio) {
      setError("Pick at least one thing to share.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await meetingOwner.addShare(sessionId, email.trim(), config);
      const added: MeetingShare = {
        email: r.email,
        granted_at: new Date().toISOString(),
        transcript: r.transcript,
        insights: r.insights,
        audio: r.audio,
        scope: r.scope,
      };
      // Re-sharing the same email updates its flags rather than duplicating.
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

      {/* Task #32 — team sharing (workspace members). Independent of the
          by-email shares below (which are for people OUTSIDE the workspace). */}
      <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4">
        <label className="flex items-center justify-between gap-3 text-xs">
          <span className="text-foreground">
            Share with everyone in this workspace
            <span className="mt-0.5 block text-muted-foreground">
              Every current and future member gets full access.
            </span>
          </span>
          <input
            type="checkbox"
            checked={sharedToWorkspace}
            onChange={toggleWorkspaceShare}
            disabled={busy || ownerOnly}
            className="h-4 w-4 accent-foreground"
            aria-label="Share with the whole workspace"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-xs">
          <span className="text-foreground">
            Keep confidential (owner-only)
            <span className="mt-0.5 block text-muted-foreground">
              Locks this meeting so it can&apos;t be shared with the workspace.
            </span>
          </span>
          <input
            type="checkbox"
            checked={ownerOnly}
            onChange={toggleOwnerOnly}
            disabled={busy}
            className="h-4 w-4 accent-foreground"
            aria-label="Keep confidential (owner-only)"
          />
        </label>
      </div>

      {visibility === "shared" ? (
        <>
          <form onSubmit={handleAddShare} className="mt-4 flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="email"
                placeholder="attendee@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={busy}
                className="min-w-[12rem] flex-1"
              />
              <Button type="submit" disabled={busy || !email.trim()}>
                Add
              </Button>
            </div>
            <fieldset
              className="flex flex-wrap gap-4"
              aria-label="What to share"
            >
              {ARTIFACTS.map((a) => (
                <label
                  key={a.key}
                  className="flex items-center gap-1.5 text-xs text-foreground"
                >
                  <input
                    type="checkbox"
                    checked={config[a.key]}
                    onChange={(e) =>
                      setConfig((c) => ({ ...c, [a.key]: e.target.checked }))
                    }
                    disabled={busy}
                    className="h-3.5 w-3.5 accent-foreground"
                  />
                  {a.label}
                </label>
              ))}
            </fieldset>
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
                    {sharedArtifacts(s).map((label) => (
                      <span
                        key={label}
                        className="rounded bg-muted px-1.5 py-0.5"
                      >
                        {label}
                      </span>
                    ))}
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
