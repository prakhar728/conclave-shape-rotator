/**
 * /search?q=… — dedicated search results page (Phase 3.5c C26).
 */
"use client";

import { Search } from "lucide-react";
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

// Starter queries shown on the empty search page — click to run. Phrased as the
// natural things people look up across meetings; they double as good /ask prompts.
const EXAMPLE_QUERIES = [
  "action items",
  "decisions we made",
  "open questions",
  "next steps",
  "deadlines mentioned",
  "what did we say about pricing",
];

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
    // New query → drop the previous /ask answer (keep "unavailable" so we
    // don't re-show the Ask button when the server flag is off).
    setAnswer((prev) => (prev === "unavailable" ? "unavailable" : null));
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
        if (!workspaceId || !q.trim()) {
          // No workspace, or empty query → nothing to search (server rejects
          // empty queries with 422 since `query` has min_length=1).
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
      <main className="mx-auto max-w-5xl px-6 py-10">
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
            className="h-12 w-full rounded-none border-2 border-foreground bg-background px-4 text-sm font-semibold tracking-wide outline-none transition-all focus:translate-x-0.5 focus:translate-y-0.5"
            autoFocus
          />
        </form>

        {/* /ask — grounded answer card (server flag-gated; hidden on 404) */}
        {q.trim() !== "" && answer !== "unavailable" ? (
          <div className="mb-6">
            {answer === null ? (
              <button
                onClick={runAsk}
                className="rounded-none border border-foreground bg-primary px-5 py-3 text-xs font-bold uppercase tracking-widest text-primary-foreground transition-all hover:bg-muted-foreground active:scale-98"
              >
                ✨ Ask your meetings this question
              </button>
            ) : answer === "loading" ? (
              <Card className="border-l-[6px] border-l-foreground">
                <CardContent className="py-5">
                  <p className="animate-shimmer-text text-sm font-bold uppercase tracking-wider">
                    Reading your meetings…
                  </p>
                  <p className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Enclave Sandbox Safe · Intel Attested
                  </p>
                </CardContent>
              </Card>
            ) : (
              <Card className="border-l-[6px] border-l-foreground">
                <CardContent className="py-5">
                  <p className="mb-3 font-mono text-[9px] font-black uppercase tracking-widest text-primary">
                    ✦ Generated Answer
                  </p>
                  <p className="text-sm leading-relaxed font-medium">{answer.answer}</p>
                  {answer.citations.length > 0 ? (
                    <p className="mt-4 flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">
                      <span>Sources:</span>
                      {Array.from(
                        new Set(answer.citations.map((c) => c.session_id)),
                      ).map((sid) => (
                        <Link
                          key={sid}
                          href={`/meeting/${sid}`}
                          className="font-mono text-xs text-primary underline underline-offset-4 hover:text-muted-foreground transition-colors"
                        >
                          {sid}
                        </Link>
                      ))}
                    </p>
                  ) : null}
                  <p className="mt-4 border-t border-border pt-3 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Computed inside TEE — plaintext is private.
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        ) : null}

        {q.trim() === "" ? (
          <div>
            <p className="mb-3 text-xs font-bold uppercase tracking-widest text-muted-foreground">
              Type a query, or try one of these
            </p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLE_QUERIES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => {
                    setInput(ex);
                    router.push(`/search?q=${encodeURIComponent(ex)}`);
                  }}
                  className="rounded-none border border-border bg-card px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : results === null ? (
          <p className="text-xs font-bold uppercase tracking-widest text-muted-foreground">Searching…</p>
        ) : results.length === 0 ? (
          <div className="rounded-none border border-dashed border-border p-10 text-center">
            <Search className="mx-auto mb-3 size-8 text-muted-foreground/40" aria-hidden />
            <p className="text-sm font-bold uppercase tracking-wide">No results for “{q}”</p>
            <p className="mt-1.5 text-xs text-muted-foreground uppercase tracking-wider font-semibold">
              Search covers transcripts of meetings in your workspace.
            </p>
          </div>
        ) : (
          <>
            <p className="mb-4 text-xs font-bold uppercase tracking-widest text-muted-foreground">
              {results.length} result{results.length === 1 ? "" : "s"} for “{q}”
            </p>
            {/* Brutalist list outline */}
            <ul className="divide-y divide-border overflow-hidden rounded-none border border-border bg-card">
              {results.map((r) => (
                <li key={r.chunk_id}>
                  <Link
                    href={`/meeting/${r.session_id}`}
                    className="group block px-5 py-5 hover:bg-secondary/40 transition-colors"
                  >
                    {r.context_header ? (
                      <p className="mb-1.5 text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
                        {r.context_header}
                      </p>
                    ) : null}
                    <p className="text-sm leading-relaxed font-semibold">
                      {highlightTerms(r.snippet, q)}
                    </p>
                    <p className="mt-3 font-mono text-[10px] font-bold uppercase tracking-wider text-muted-foreground transition-colors group-hover:text-primary">
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
