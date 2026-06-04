/**
 * /search?q=… — dedicated search results page (Phase 3.5c C26).
 */
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { Card, CardContent } from "@/components/ui/card";
import {
  ApiError,
  auth,
  search,
  type MeResponse,
  type SearchResult,
} from "@/lib/api";

export default function SearchPage() {
  return (
    <Suspense>
      <SearchPageInner />
    </Suspense>
  );
}

function SearchPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  const q = params.get("q") ?? "";
  const [me, setMe] = useState<MeResponse | null>(null);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState(q);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
        if (!meResp.workspace || !q.trim()) {
          setResults([]);
          return;
        }
        const resp = await search.query(meResp.workspace.id, q.trim(), 30);
        if (!cancelled) setResults(resp.results);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Search failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, q]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    );
  }
  if (!me) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <AppHeader user={me.user} workspace={me.workspace} />
      <main className="mx-auto max-w-3xl px-6 py-10">
        <form
          className="mb-8"
          onSubmit={(e) => {
            e.preventDefault();
            if (input.trim())
              router.push(`/search?q=${encodeURIComponent(input.trim())}`);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Search across your meetings…"
            className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-foreground/40"
            autoFocus
          />
        </form>

        {q.trim() === "" ? (
          <p className="text-sm text-muted-foreground">
            Type a query to search across your meetings.
          </p>
        ) : results === null ? (
          <p className="text-sm text-muted-foreground">Searching…</p>
        ) : results.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center">
            <p className="text-sm font-medium">No results for “{q}”</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Search covers transcripts of meetings you can see.
            </p>
          </div>
        ) : (
          <>
            <p className="mb-4 text-sm text-muted-foreground">
              {results.length} result{results.length === 1 ? "" : "s"} for “{q}”
            </p>
            <ul className="flex flex-col gap-3">
              {results.map((r) => (
                <li key={r.chunk_id}>
                  <Link href={`/meeting/${r.session_id}`}>
                    <Card className="transition-colors hover:border-foreground/20">
                      <CardContent className="py-3">
                        {r.context_header ? (
                          <p className="mb-1 text-[11px] italic text-muted-foreground">
                            {r.context_header}
                          </p>
                        ) : null}
                        <p className="text-sm">{r.snippet}</p>
                        <p className="mt-2 text-xs text-muted-foreground">
                          {r.meeting.date ?? ""}
                          {r.meeting.summary
                            ? ` · ${truncate(r.meeting.summary, 70)}`
                            : ""}
                        </p>
                      </CardContent>
                    </Card>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </main>
    </div>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
