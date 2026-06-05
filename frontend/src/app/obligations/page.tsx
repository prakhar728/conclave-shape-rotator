/**
 * /obligations — workspace obligations board (Phase 3.5b C22).
 *
 * Replaces v1's "Open Questions" board: every current obligation
 * (bi-temporally live, valid_to IS NULL server-side) across meetings
 * the caller can see, grouped by type with status + type filters.
 * Sorted by importance server-side.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { PageError, PageLoading } from "@/components/page-state";
import {
  ApiError,
  auth,
  kb,
  type KBObligation,
  type MeResponse,
} from "@/lib/api";

const TYPES = [
  "action",
  "decision",
  "commitment",
  "open_question",
  "blocker",
] as const;
const STATUSES = ["open", "resolved", "unclear"] as const;

/**
 * One color per obligation type (UI-NOW.md §3): the board should be
 * glanceable — a wall of same-gray chips isn't. All via theme tokens.
 */
const TYPE_CHIP: Record<string, string> = {
  action: "border-primary/40 bg-primary/10 text-primary",
  decision: "border-signal-entity/40 bg-signal-entity/10 text-signal-entity",
  commitment: "border-accent-mint/40 bg-accent-mint/10 text-accent-mint",
  open_question:
    "border-signal-speaker/40 bg-signal-speaker/10 text-signal-speaker",
  blocker: "border-destructive/40 bg-destructive/10 text-destructive",
};

/** open = needs attention (amber), resolved = done (emerald), unclear = muted. */
const STATUS_PILL: Record<string, string> = {
  open: "border-signal-speaker/40 text-signal-speaker",
  resolved: "border-primary/40 text-primary",
  unclear: "border-border text-muted-foreground",
};

export default function ObligationsPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [obligations, setObligations] = useState<KBObligation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
        if (!meResp.workspace) {
          setObligations([]);
          return;
        }
        const resp = await kb.obligations(meResp.workspace.id);
        if (!cancelled) setObligations(resp.obligations);
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
    if (!obligations) return null;
    let out = obligations;
    if (typeFilter) out = out.filter((o) => o.type === typeFilter);
    if (statusFilter) out = out.filter((o) => o.status_inferred === statusFilter);
    return out;
  }, [obligations, typeFilter, statusFilter]);

  if (error) return <PageError message={error} />;
  if (!me) return <PageLoading />;

  return (
    <div className="min-h-screen bg-background">
      <AppHeader user={me.user} workspace={me.workspace} />
      <main className="mx-auto max-w-3xl px-6 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-bold tracking-tight">
            Obligations
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {visible === null
              ? "Loading…"
              : `${visible.length} current across your meetings.`}
          </p>
        </div>

        <div className="mb-6 flex flex-wrap items-center gap-2">
          {TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(typeFilter === t ? null : t)}
              className={`rounded-full border px-3 py-1 text-xs capitalize transition-colors ${
                typeFilter === t
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.replace("_", " ")}
            </button>
          ))}
          <span className="mx-1 text-border">|</span>
          {STATUSES.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(statusFilter === s ? null : s)}
              className={`rounded-full border px-3 py-1 text-xs capitalize transition-colors ${
                statusFilter === s
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        {visible === null ? (
          <p className="text-sm text-muted-foreground">Loading obligations…</p>
        ) : visible.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center">
            <p className="text-sm font-medium">Nothing here yet</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Obligations appear once the knowledge pipeline processes your
              meetings{typeFilter || statusFilter ? " — or try clearing the filters" : ""}.
            </p>
          </div>
        ) : (
          /* Editorial Vault: hairline rows; the type chip carries the color,
             the description carries the typography. */
          <ul className="divide-y divide-border border-t border-border">
            {visible.map((o) => (
              <li key={o.id}>
                <Link
                  href={`/meeting/${o.session_id}`}
                  className="group block py-5"
                >
                  <p className="text-base font-semibold leading-snug transition-colors group-hover:text-primary">
                    {o.description}
                  </p>
                  <div className="mt-2.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span
                      className={`rounded-full border px-2 py-0.5 capitalize ${
                        TYPE_CHIP[o.type] ?? "border-border text-foreground"
                      }`}
                    >
                      {o.type.replace("_", " ")}
                    </span>
                    <span
                      className={`rounded-full border px-2 py-0.5 capitalize ${
                        STATUS_PILL[o.status_inferred] ??
                        "border-border text-muted-foreground"
                      }`}
                    >
                      {o.status_inferred}
                    </span>
                    {o.owner_raw_text ? (
                      <>
                        <span>·</span>
                        <span>{o.owner_raw_text}</span>
                      </>
                    ) : null}
                    {o.due_date_raw ? (
                      <>
                        <span>·</span>
                        <span className="font-mono">due {o.due_date_raw}</span>
                      </>
                    ) : null}
                    {o.importance ? (
                      <span className="ml-auto inline-flex items-center gap-1.5">
                        <span
                          className="h-1 w-12 overflow-hidden rounded-full bg-muted"
                          aria-hidden
                        >
                          <span
                            className="block h-full rounded-full bg-primary"
                            style={{
                              width: `${o.importance * 10}%`,
                            }}
                          />
                        </span>
                        <span className="font-mono text-[10px]">
                          {o.importance}/10
                        </span>
                      </span>
                    ) : null}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
