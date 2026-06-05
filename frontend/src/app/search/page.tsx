/**
 * /search?q=… — dedicated search results page (Phase 3.5c C26).
 */
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { useWorkspace } from "@/components/workspace-provider";
import { Card, CardContent } from "@/components/ui/card";
import {
  ApiError,
  ask,
  auth,
  search,
  type AskResponse,
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
  const { workspace, workspaces: wsList } = useWorkspace();
  const workspaceId = workspace?.id ?? null;
  const [me, setMe] = useState<MeResponse | null>(null);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState(q);
  // /ask: null = not requested, "loading", "unavailable" (flag off), or response
  const [answer, setAnswer] = useState<AskResponse | "loading" | "unavailable" | null>(null);

  async function runAsk() {
    if (!workspaceId || !q.trim()) return;
    setAnswer("loading");
    try {
      const resp = await ask.question(workspaceId, q.trim());
      setAnswer(resp);
    } catch (err) {
      // 404 = ENABLE_ASK off server-side → hide the feature quietly
      setAnswer(err instanceof ApiError && err.status === 404 ? "unavailable" : null);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
        if (!workspaceId) {
          setResults([]);
          return;
        }
        const resp = await search.query(workspaceId, q.trim(), 30);
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
  }, [router, q, workspaceId]);

  if (error) return <PageError message={error} />;
  if (!me || wsList === null) return <PageLoading />;

  return (
    <AppShell user={me.user}>
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
            className="h-10 w-full rounded-md border border-border bg-background px-3 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            autoFocus
          />
        </form>

        {/* /ask — grounded answer card (server flag-gated; hidden on 404) */}
        {q.trim() !== "" && answer !== "unavailable" ? (
          <div className="mb-6">
            {answer === null ? (
              <button
                onClick={runAsk}
                className="rounded-md border border-primary/50 bg-primary/5 px-3.5 py-2 text-xs font-medium text-primary transition-all hover:bg-primary hover:text-primary-foreground hover:shadow-[0_0_24px_-8px_var(--primary)]"
              >
                ✨ Ask your meetings this question
              </button>
            ) : answer === "loading" ? (
              <Card className="border-l-2 border-l-primary">
                <CardContent className="py-4">
                  <p className="animate-shimmer-text text-sm font-medium">
                    Reading your meetings…
                  </p>
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    Runs inside the enclave — no third-party LLM sees your
                    query.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <Card className="border-l-2 border-l-primary">
                <CardContent className="py-4">
                  <p className="mb-2 font-mono text-[10px] uppercase tracking-widest text-primary">
                    ✦ generated answer
                  </p>
                  <p className="text-sm leading-relaxed">{answer.answer}</p>
                  {answer.citations.length > 0 ? (
                    <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span>Sources:</span>
                      {Array.from(
                        new Set(answer.citations.map((c) => c.session_id)),
                      ).map((sid) => (
                        <Link
                          key={sid}
                          href={`/meeting/${sid}`}
                          className="font-mono text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary"
                        >
                          {sid}
                        </Link>
                      ))}
                    </p>
                  ) : null}
                  <p className="mt-3 border-t border-border pt-2 text-[11px] text-muted-foreground">
                    Generated inside the enclave — this answer never left your
                    workspace.
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        ) : null}

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
            <p className="mb-2 text-sm text-muted-foreground">
              {results.length} result{results.length === 1 ? "" : "s"} for “{q}”
            </p>
            {/* Editorial Vault: hairline rows; matched terms get a mint wash. */}
            <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card shadow-sm">
              {results.map((r) => (
                <li key={r.chunk_id}>
                  <Link
                    href={`/meeting/${r.session_id}`}
                    className="group block px-5 py-5"
                  >
                    {r.context_header ? (
                      <p className="mb-1.5 text-xs italic text-muted-foreground">
                        {r.context_header}
                      </p>
                    ) : null}
                    <p className="text-sm leading-relaxed">
                      {highlightTerms(r.snippet, q)}
                    </p>
                    <p className="mt-2 font-mono text-xs text-muted-foreground transition-colors group-hover:text-primary">
                      {r.meeting.date ?? ""}
                      {r.meeting.summary
                        ? ` · ${truncate(r.meeting.summary, 70)}`
                        : ""}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </main>
    </AppShell>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Wrap query-term matches in a mint-washed <mark> so the user can see
 * *why* a snippet matched (UI-NOW.md §3, search P1). Terms under 3 chars
 * are skipped — highlighting "a"/"of" is noise, not signal.
 */
function highlightTerms(text: string, query: string): React.ReactNode {
  const terms = Array.from(
    new Set(
      query
        .toLowerCase()
        .split(/\s+/)
        .filter((t) => t.length > 2)
        .map(escapeRegExp),
    ),
  );
  if (terms.length === 0) return text;
  // Single capture group → matches land at odd indices after split.
  const parts = text.split(new RegExp(`(${terms.join("|")})`, "gi"));
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <mark
        key={i}
        className="rounded-[3px] bg-primary/20 px-0.5 text-foreground"
      >
        {part}
      </mark>
    ) : (
      part
    ),
  );
}
