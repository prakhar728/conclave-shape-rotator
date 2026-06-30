/**
 * Admin feedback inbox (Task #19) — the operator-blind read path: instead of a
 * DB shell into the TEE, an admin pulls submitted feedback over the authenticated
 * API. Server-gated by CONCLAVE_ADMIN_EMAILS; a 403 here means the account isn't
 * on the allowlist.
 *
 * Self-contained (fetch + states) so it can be unit-tested by mocking feedback.list.
 */
"use client";

import { useEffect, useState } from "react";

import { ApiError, feedback, type FeedbackItem } from "@/lib/api";

const CATEGORY_LABEL: Record<string, string> = {
  feature: "Feature",
  bug: "Bug",
  other: "Other",
};

export function FeedbackInbox() {
  const [items, setItems] = useState<FeedbackItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await feedback.list();
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 403) {
          setForbidden(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load feedback");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (forbidden) {
    return (
      <p data-testid="feedback-forbidden" className="text-sm text-muted-foreground">
        You don&rsquo;t have access to the feedback inbox.
      </p>
    );
  }
  if (error) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (items === null) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }
  if (items.length === 0) {
    return (
      <p data-testid="feedback-empty" className="text-sm text-muted-foreground">
        No feedback yet.
      </p>
    );
  }

  return (
    <div data-testid="feedback-inbox">
      <p className="mb-3 text-xs text-muted-foreground">{total} total</p>
      <ul className="space-y-3">
        {items.map((it) => (
          <li
            key={it.id}
            className="rounded-lg border border-border bg-card p-4"
          >
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded border border-border px-1.5 py-0.5 font-medium text-foreground">
                {CATEGORY_LABEL[it.category] ?? it.category}
              </span>
              <span className="font-mono">{it.user_email}</span>
              <span>·</span>
              <span>{new Date(it.created_at).toLocaleString()}</span>
              {it.page_context ? (
                <>
                  <span>·</span>
                  <code className="font-mono">{it.page_context}</code>
                </>
              ) : null}
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm text-foreground">
              {it.body}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
