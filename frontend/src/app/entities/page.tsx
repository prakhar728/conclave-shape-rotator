/**
 * /entities — workspace entity list (Phase 3.5b C20).
 *
 * Every entity mentioned in meetings the caller can see, sorted by
 * mention count. Type chips filter client-side over the fetched set
 * (the endpoint supports ?type= but one fetch + local filter is
 * snappier for v1 corpus sizes). Rows link to /entity/[name].
 */
"use client";

import { Tags } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { useWorkspace } from "@/components/workspace-provider";
import { entityTint } from "@/lib/entity-tints";
import {
  ApiError,
  auth,
  kb,
  type KBEntity,
  type MeResponse,
} from "@/lib/api";

// OI-7 derived 3-category model (was the 5 fine types). Filters on `category`.
const TYPES = ["person", "tech", "affiliation"] as const;

export default function EntitiesPage() {
  const router = useRouter();
  const { workspace, workspaces: wsList } = useWorkspace();
  const workspaceId = workspace?.id ?? null;
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
        if (!workspaceId) {
          setEntities([]);
          return;
        }
        const resp = await kb.entities(workspaceId);
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
  }, [router, workspaceId]);

  const visible = useMemo(() => {
    if (!entities) return null;
    let out = entities;
    if (typeFilter) out = out.filter((e) => e.category === typeFilter);
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
  if (!me || wsList === null) return <PageLoading />;

  return (
    <AppShell user={me.user}>
      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="mb-8">
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight md:text-3xl">
            <Tags className="size-6 shrink-0 text-muted-foreground" aria-hidden />
            Entities
          </h1>
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
            className="h-8 w-48 rounded-none border border-border bg-background px-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(typeFilter === t ? null : t)}
              className={`rounded-none border px-3 py-1 text-xs capitalize transition-colors ${
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
          <div className="rounded-none border border-dashed border-border p-10 text-center">
            <Tags className="mx-auto mb-3 size-8 text-muted-foreground/40" aria-hidden />
            <p className="text-sm font-medium">No entities yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Entities appear here once the knowledge pipeline processes
              your meetings.
            </p>
          </div>
        ) : (
          /* Compact hairline ledger rows: the type chip
             carries the entity color language, counts go mono. */
          <ul className="divide-y divide-border overflow-hidden rounded-none border border-border bg-card">
            {visible.map((e) => (
              <li key={e.id}>
                <Link
                  href={`/entity/${encodeURIComponent(e.canonical_name)}`}
                  className="group flex items-center justify-between gap-4 px-5 py-3.5"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span
                      className={`shrink-0 rounded-none border px-2 py-0.5 text-xs capitalize ${entityTint(e.category)}`}
                    >
                      {e.category}
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
    </AppShell>
  );
}
