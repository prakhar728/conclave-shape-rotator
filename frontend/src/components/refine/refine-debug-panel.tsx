"use client";

import { useCallback, useEffect, useState } from "react";

import { refine, type V2Debug } from "@/lib/api";

/**
 * Dev-only "backend state" panel — re-fetches GET /debug from the server (the
 * persisted truth, not local optimistic state) so an edit/tag can be SEEN to land
 * where Part 2 reads it. Shown on /refine when ?debug=1. Auto-refreshes whenever
 * `refreshKey` bumps (the page bumps it after each edit) + a manual Refresh.
 */
export function RefineDebugPanel({
  sessionId,
  refreshKey,
}: {
  sessionId: string;
  refreshKey?: number;
}) {
  const [data, setData] = useState<V2Debug | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    refine
      .debug(sessionId)
      .then((d) => {
        setData(d);
        setErr(null);
      })
      .catch((e) => setErr(e?.message ?? "failed to load backend state"));
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  return (
    <aside
      data-testid="debug-panel"
      className="mt-6 rounded-md border border-dashed border-border bg-muted/30 p-3 text-xs"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="font-bold uppercase tracking-wide text-muted-foreground">
          Backend state (live) — what actually persisted
        </span>
        <button
          data-testid="debug-refresh"
          onClick={load}
          className="rounded border border-border px-2 py-0.5 hover:bg-accent"
        >
          Refresh
        </button>
      </div>

      {err ? <p className="text-destructive">{err}</p> : null}
      {!data ? (
        <p className="text-muted-foreground">loading…</p>
      ) : (
        <div className="space-y-2">
          <p>
            status: <b>{data.status}</b> · stale: <b>{String(data.insights_stale)}</b> · trust:{" "}
            <b>{data.trust_state}</b>
          </p>
          <div>
            <p className="font-semibold">annotations ({data.annotations.length}) — Part 2 priors</p>
            <ul className="ml-3 list-disc">
              {data.annotations.map((a, i) => (
                <li key={i}>
                  {a.surface} — {a.type ?? "—"} ({a.state}, {a.source})
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="font-semibold">vocab ({data.vocab.length}) — your dictionary</p>
            <ul className="ml-3 list-disc">
              {data.vocab.map((v, i) => (
                <li key={i}>
                  {v.surface} — {v.type ?? "—"} ({v.provenance})
                </li>
              ))}
            </ul>
          </div>
          <p>
            entity graph: <b>{data.entity_count ?? "—"}</b> entities · <b>{data.fact_count ?? "—"}</b> facts
          </p>
        </div>
      )}
    </aside>
  );
}
