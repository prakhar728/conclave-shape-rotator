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
import { Card, CardContent } from "@/components/ui/card";
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
        <div className="mb-6">
          <h1 className="text-3xl font-semibold tracking-tight">Entities</h1>
          <p className="mt-1 text-sm text-muted-foreground">
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
            className="h-8 w-48 rounded-md border border-border bg-background px-2 text-sm outline-none focus:border-foreground/40"
          />
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(typeFilter === t ? null : t)}
              className={`rounded-full border px-3 py-1 text-xs capitalize transition-colors ${
                typeFilter === t
                  ? "border-foreground bg-foreground text-background"
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
          <ul className="flex flex-col gap-2">
            {visible.map((e) => (
              <li key={e.id}>
                <Link href={`/entity/${encodeURIComponent(e.canonical_name)}`}>
                  <Card className="transition-colors hover:border-foreground/20">
                    <CardContent className="flex items-center justify-between py-3">
                      <div className="flex items-center gap-3">
                        <span className="rounded-full border border-border px-2 py-0.5 text-xs capitalize text-muted-foreground">
                          {e.type}
                        </span>
                        <span className="text-sm font-medium">
                          {e.canonical_name}
                        </span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {e.mention_count}{" "}
                        {e.mention_count === 1 ? "mention" : "mentions"} ·{" "}
                        {e.meeting_count}{" "}
                        {e.meeting_count === 1 ? "meeting" : "meetings"}
                      </span>
                    </CardContent>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
