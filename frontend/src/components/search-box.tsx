/**
 * Header search box with typeahead dropdown (Phase 3.5c C26).
 *
 * Debounced 250ms; top-5 results inline, Enter (or "see all") goes to
 * /search?q=…. Closes on blur/escape/navigate. Hidden when there is
 * no workspace (nothing to search).
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { search, type SearchResult } from "@/lib/api";

export function SearchBox({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    if (!q.trim()) return; // clearing is handled in onChange, not here
    timer.current = setTimeout(async () => {
      try {
        const resp = await search.query(workspaceId, q.trim(), 5);
        setResults(resp.results);
        setOpen(true);
      } catch {
        setResults([]);
        setOpen(true);
      }
    }, 250);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [q, workspaceId]);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function goToFullSearch() {
    if (!q.trim()) return;
    setOpen(false);
    router.push(`/search?q=${encodeURIComponent(q.trim())}`);
  }

  return (
    <div ref={boxRef} className="relative hidden md:block">
      <input
        value={q}
        onChange={(e) => {
          const v = e.target.value;
          setQ(v);
          if (!v.trim()) {
            setResults(null);
            setOpen(false);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") goToFullSearch();
          if (e.key === "Escape") setOpen(false);
        }}
        onFocus={() => results && setOpen(true)}
        placeholder="Search meetings…"
        className="h-8 w-56 rounded-none border border-border bg-background px-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
      />
      {open && results !== null ? (
        <div className="absolute left-0 top-9 z-50 w-96 rounded-none border border-border bg-background">
          {results.length === 0 ? (
            <p className="p-3 text-xs text-muted-foreground">No matches.</p>
          ) : (
            <ul>
              {results.map((r) => (
                <li key={r.chunk_id} className="border-b border-border last:border-0">
                  <Link
                    href={`/meeting/${r.session_id}`}
                    onClick={() => setOpen(false)}
                    className="block p-3 hover:bg-accent"
                  >
                    <p className="line-clamp-2 text-xs">{r.snippet}</p>
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      {r.meeting.date ?? r.session_id}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <button
            onClick={goToFullSearch}
            className="block w-full border-t border-border p-2 text-center text-xs text-muted-foreground hover:text-foreground"
          >
            See all results ↵
          </button>
        </div>
      ) : null}
    </div>
  );
}
