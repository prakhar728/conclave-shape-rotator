/**
 * /entities — workspace entity list (Phase 3.5b C20).
 *
 * Every entity mentioned in meetings the caller can see, sorted by
 * mention count. Type chips filter client-side over the fetched set
 * (the endpoint supports ?type= but one fetch + local filter is
 * snappier for v1 corpus sizes). Rows link to /entity/[name].
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { PageError, PageLoading } from "@/components/page-state";
import { entityTint } from "@/lib/entity-tints";
import {
  ApiError,
  auth,
  kb,
  type KBEntity,
  type MeResponse,
} from "@/lib/api";

const TYPES = ["person", "project", "topic", "company", "tool"] as const;

export default function EntitiesPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [entities, setEntities] = useState<KBEntity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
        if (!meResp.workspace) {
          setEntities([]);
          return;
        }
        const resp = await kb.entities(meResp.workspace.id);
        if (!cancelled) setEntities(resp.entities);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  const visible = useMemo(() => {
    if (!entities) return null;
    let out = entities;
    if (typeFilter) out = out.filter((e) => e.type === typeFilter);
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      out = out.filter(
        (e) =>
          e.canonical_name.toLowerCase().includes(q) ||
          e.raw_mentions.some((m) => m.toLowerCase().includes(q)),
      );
    }
    return out;
  }, [entities, typeFilter, query]);

  if (error) return <PageError message={error} />;
  if (!me) return <PageLoading />;

  return (
    <div className="min-h-screen bg-background">
      <AppHeader user={me.user} workspace={me.workspace} />
      <main className="mx-auto max-w-3xl px-6 py-10">
        <div className="mb-8">
          <h1 className="font-heading text-4xl tracking-tight">Entities</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {visible === null
              ? "Loading…"
              : `${visible.length} across your meetings.`}
          </p>
        </div>

        <div className="mb-6 flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by name…"
            className="h-8 w-48 rounded-md border border-border bg-background px-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(typeFilter === t ? null : t)}
              className={`rounded-full border px-3 py-1 text-xs capitalize transition-colors ${
                typeFilter === t
                  ? entityTint(t)
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {visible === null ? (
          <p className="text-sm text-muted-foreground">Loading entities…</p>
        ) : visible.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center">
            <p className="text-sm font-medium">No entities yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Entities appear here once the knowledge pipeline processes
              your meetings.
            </p>
          </div>
        ) : (
          /* Editorial Vault: compact hairline ledger rows; the type chip
             carries the entity color language, counts go mono. */
          <ul className="divide-y divide-border border-t border-border">
            {visible.map((e) => (
              <li key={e.id}>
                <Link
                  href={`/entity/${encodeURIComponent(e.canonical_name)}`}
                  className="group flex items-center justify-between gap-4 py-3.5"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span
                      className={`shrink-0 rounded-full border px-2 py-0.5 text-xs capitalize ${entityTint(e.type)}`}
                    >
                      {e.type}
                    </span>
                    <span className="truncate text-sm font-medium transition-colors group-hover:text-primary">
                      {e.canonical_name}
                    </span>
                  </div>
                  <span className="shrink-0 font-mono text-xs text-muted-foreground">
                    {e.mention_count}×{" · "}
                    {e.meeting_count}{" "}
                    {e.meeting_count === 1 ? "meeting" : "meetings"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
