/**
 * Feedback form (Task #19) — category dropdown + body textarea + a hidden
 * page-context (the route the user came from). Posts to /api/feedback, which
 * writes a row and best-effort emails the team. Success/error states inline.
 *
 * Extracted from the /feedback page so it can be unit-tested in isolation
 * (mirrors upload-transcript.tsx / retention-control.tsx).
 */
"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { feedback, type FeedbackCategory } from "@/lib/api";

const CATEGORY_OPTIONS: { value: FeedbackCategory; label: string }[] = [
  { value: "feature", label: "Feature request" },
  { value: "bug", label: "Bug report" },
  { value: "other", label: "Other" },
];

export function FeedbackForm({
  pageContext,
  workspaceId,
}: {
  pageContext?: string | null;
  workspaceId?: string | null;
}) {
  const [category, setCategory] = useState<FeedbackCategory>("feature");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await feedback.submit({
        category,
        body: body.trim(),
        page_context: pageContext ?? null,
        workspace_id: workspaceId ?? null,
      });
      setSent(true);
      setBody("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send feedback");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div
        data-testid="feedback-success"
        className="rounded-lg border border-border bg-card p-5"
      >
        <h2 className="text-sm font-medium">Thanks for the feedback.</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          It went straight to the team. We read every submission.
        </p>
        <Button
          type="button"
          variant="outline"
          className="mt-4"
          onClick={() => {
            setSent(false);
            setError(null);
          }}
        >
          Send more
        </Button>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-lg border border-border bg-card p-5"
    >
      <label className="block text-sm font-medium" htmlFor="feedback-category">
        Type
      </label>
      <select
        id="feedback-category"
        value={category}
        onChange={(e) => setCategory(e.target.value as FeedbackCategory)}
        disabled={busy}
        aria-label="Feedback type"
        className="mt-2 h-9 w-full rounded-md border border-border bg-background px-2 text-sm text-foreground"
      >
        {CATEGORY_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      <label
        className="mt-5 block text-sm font-medium"
        htmlFor="feedback-body"
      >
        What&rsquo;s on your mind?
      </label>
      <textarea
        id="feedback-body"
        value={body}
        onChange={(e) => {
          setBody(e.target.value);
          setError(null);
        }}
        disabled={busy}
        rows={6}
        placeholder="A feature you wish existed, a bug you hit, anything…"
        aria-label="Feedback body"
        className="mt-2 w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground"
      />

      {pageContext ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Sent with context from{" "}
          <code className="font-mono">{pageContext}</code>
        </p>
      ) : null}

      <div className="mt-4 flex items-center gap-3">
        <Button type="submit" disabled={busy || !body.trim()}>
          {busy ? "Sending…" : "Send feedback"}
        </Button>
        {error ? (
          <span className="text-xs text-destructive">{error}</span>
        ) : null}
      </div>
    </form>
  );
}
