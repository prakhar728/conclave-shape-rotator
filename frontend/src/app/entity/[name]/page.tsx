/**
 * /entity/[name] — entity detail (Phase 3.5b C21).
 *
 * Meta + meetings the entity appears in (visible-to-caller only,
 * enforced server-side) + related current obligations. The [name]
 * segment is the URL-encoded canonical name; the backend matches it
 * case-insensitively.
 */
"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { entityTint } from "@/lib/entity-tints";
import {
  ApiError,
  auth,
  kb,
  type KBEntityDetail,
  type MeResponse,
} from "@/lib/api";

export default function EntityDetailPage() {
  const router = useRouter();
  const params = useParams<{ name: string }>();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [detail, setDetail] = useState<KBEntityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
        if (!meResp.workspace) {
          setNotFound(true);
          return;
        }
        const name = decodeURIComponent(params.name);
        const resp = await kb.entity(meResp.workspace.id, name);
        if (!cancelled) setDetail(resp);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, params.name]);

  if (error) return <PageError message={error} />;
  if (!me) return <PageLoading />;

  return (
    <AppShell user={me.user} workspace={me.workspace}>
      <main className="mx-auto max-w-3xl px-6 py-10">
        {notFound ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center">
            <p className="text-sm font-medium">Entity not found</p>
            <p className="mt-1 text-xs text-muted-foreground">
              It may not appear in any meeting you can see.{" "}
              <Link href="/entities" className="underline">
                Back to entities
              </Link>
            </p>
          </div>
        ) : detail === null ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <>
            <div className="mb-10">
              <div className="flex items-baseline gap-3">
                <h1 className="font-serif text-3xl md:text-4xl">
                  {detail.entity.canonical_name}
                </h1>
                <span
                  className={`rounded-full border px-2 py-0.5 text-xs capitalize ${entityTint(detail.entity.type)}`}
                >
                  {detail.entity.type}
                </span>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                <span className="font-mono text-xs">
                  {detail.entity.mention_count}×
                </span>{" "}
                {detail.entity.mention_count === 1 ? "mention" : "mentions"}
                {detail.entity.raw_mentions.length > 1 ? (
                  <>
                    {" "}
                    · also seen as{" "}
                    <span className="italic">
                      {detail.entity.raw_mentions.join(", ")}
                    </span>
                  </>
                ) : null}
              </p>
            </div>

            <section className="mb-10">
              <h2 className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
                Meetings
              </h2>
              {detail.meetings.length === 0 ? (
                <p className="text-sm text-muted-foreground">None visible.</p>
              ) : (
                <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card shadow-sm">
                  {detail.meetings.map((m) => (
                    <li key={m.session_id}>
                      <Link
                        href={`/meeting/${m.session_id}`}
                        className="group flex items-center justify-between gap-3 px-5 py-3.5"
                      >
                        <span className="text-sm transition-colors group-hover:text-primary">
                          {m.summary ? truncate(m.summary, 80) : m.session_id}
                        </span>
                        <span className="shrink-0 font-mono text-xs text-muted-foreground">
                          {m.date ?? ""} · {m.turn_ids.length}{" "}
                          {m.turn_ids.length === 1 ? "turn" : "turns"}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section>
              <h2 className="mb-3 text-xs uppercase tracking-[0.2em] text-muted-foreground">
                Obligations
              </h2>
              {detail.obligations.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  None currently owned by this entity.
                </p>
              ) : (
                <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card shadow-sm">
                  {detail.obligations.map((o) => (
                    <li key={o.id} className="px-5 py-3.5">
                      <p className="text-sm leading-relaxed">
                        {o.description}
                      </p>
                      <p className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
                        <span className="rounded-full border border-border px-2 py-0.5 capitalize">
                          {o.type.replace("_", " ")}
                        </span>
                        <span className="capitalize">{o.status_inferred}</span>
                        {o.due_date_raw ? (
                          <span className="font-mono">
                            · due {o.due_date_raw}
                          </span>
                        ) : null}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </main>
    </AppShell>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
