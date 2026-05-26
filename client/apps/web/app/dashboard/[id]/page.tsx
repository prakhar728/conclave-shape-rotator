"use client"

import * as React from "react"
import { use } from "react"
import Link from "next/link"
import {
  ArrowLeft,
  ArrowsClockwise,
  Cube,
  ClockClockwise,
  CheckCircle,
  Warning,
  CircleNotch,
} from "@phosphor-icons/react"

import { api, ApiError } from "@/lib/api"
import { Laurel, SpqrSeal } from "@/components/seal-marks"
import { MobileDrawer } from "@/components/mobile-drawer"
import type {
  Attestation,
  CohortAggregates,
  CohortTimelineEntry,
  NoveltyResult,
  StoredInstance,
  SubmissionMeta,
} from "@/lib/types"

type Tab = "cohort" | "submissions" | "attestations"

interface DashboardData {
  aggregates: CohortAggregates
  timeline: CohortTimelineEntry[]
  submissions: SubmissionMeta[]
  results: NoveltyResult[]
  attestations: Attestation[]
}

export default function DashboardPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: instanceId } = use(params)
  const [token, setToken] = React.useState<string | null>(null)
  const [data, setData] = React.useState<DashboardData | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [tab, setTab] = React.useState<Tab>("cohort")
  const [busy, setBusy] = React.useState<"trigger" | "publish" | null>(null)
  const [instanceName, setInstanceName] = React.useState<string>("")

  React.useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem("conclave.instances") || "[]") as StoredInstance[]
      const match = stored.find((s) => s.instance_id === instanceId)
      if (match) {
        setToken(match.admin_token)
        setInstanceName(match.name)
      }
    } catch {
      // ignore
    }
  }, [instanceId])

  const load = React.useCallback(async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const [agg, timeline, subs, results, atts] = await Promise.all([
        api.cohortAggregates(token),
        api.cohortTimeline(token),
        api.listSubmissions(token),
        api.listResults(token),
        api.listAttestations(token),
      ])
      setData({
        aggregates: agg,
        timeline: timeline.runs,
        submissions: subs.submissions,
        results: results.results,
        attestations: atts.attestations,
      })
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
    } finally {
      setLoading(false)
    }
  }, [token])

  React.useEffect(() => {
    if (token) void load()
  }, [token, load])

  async function triggerEvaluation() {
    if (!token) return
    setBusy("trigger")
    try {
      await api.triggerPipeline(token)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
    } finally {
      setBusy(null)
    }
  }

  async function publishAttestation() {
    if (!token) return
    setBusy("publish")
    try {
      await api.publishAttestation(token)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
    } finally {
      setBusy(null)
    }
  }

  if (!token) {
    return <TokenPrompt instanceId={instanceId} onSubmit={setToken} />
  }

  return (
    <div className="min-h-screen arena-bg text-foreground pb-24 md:pb-0">
      <Nav instanceName={instanceName || instanceId} />
      <main className="mx-auto max-w-6xl px-4 sm:px-6 py-6 sm:py-10 space-y-6 sm:space-y-8">
        <header className="flex flex-col md:flex-row md:items-start md:justify-between gap-4 md:gap-6">
          <div className="space-y-2 min-w-0">
            <div className="bracket-label">THE ARENA · OPERATOR VIEW</div>
            <h1 className="font-display text-2xl sm:text-3xl md:text-4xl tracking-wide uppercase break-words">
              {instanceName || "Hackathon"}
            </h1>
            <div className="gold-rule w-24" />
            <div className="font-mono text-[11px] sm:text-xs text-muted-foreground break-all">{instanceId}</div>
          </div>
          {/* Desktop / tablet action row */}
          <div className="hidden md:flex items-center gap-2 flex-wrap">
            <button
              onClick={() => void load()}
              disabled={loading}
              className="touch-target-sm inline-flex items-center gap-1.5 rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono uppercase tracking-wider hover:border-foreground transition-colors disabled:opacity-50"
            >
              {loading ? <CircleNotch className="size-3.5 animate-spin" /> : <ArrowsClockwise className="size-3.5" />}
              Refresh
            </button>
            <button
              onClick={triggerEvaluation}
              disabled={busy !== null}
              title="Runs the full skill pipeline over the cohort. The first run after a server restart can take ~30-60s while the embedding model loads."
              className="touch-target-sm inline-flex items-center gap-1.5 rounded-sm border border-foreground bg-foreground px-3 py-2 text-xs font-mono uppercase tracking-wider text-background hover:bg-primary hover:border-primary transition-colors disabled:opacity-50"
            >
              {busy === "trigger" ? <CircleNotch className="size-3.5 animate-spin" /> : <Cube className="size-3.5" />}
              {busy === "trigger" ? "Deliberating…" : "Trigger Deliberation"}
            </button>
            <button
              onClick={publishAttestation}
              disabled={busy !== null}
              className="touch-target-sm inline-flex items-center gap-1.5 rounded-sm border border-primary bg-primary px-3 py-2 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {busy === "publish" ? <CircleNotch className="size-3.5 animate-spin" /> : <Laurel className="size-3.5" color="currentColor" />}
              Affix the Seal
            </button>
          </div>
        </header>

        {busy === "trigger" && (
          <div className="rounded-sm border border-border bg-muted/40 px-4 py-3 text-sm font-serif italic flex items-center gap-2">
            <CircleNotch className="size-4 shrink-0 animate-spin" />
            <span>
              Deliberation in progress. The pipeline runs embeddings, clustering, and per-submission LLM passes —
              the first run after a server restart can take 30–60 seconds while the model loads. The button will
              clear when the run completes.
            </span>
          </div>
        )}

        {error && (
          <div
            className="rounded-sm border px-4 py-3 text-sm font-serif italic flex items-center gap-2"
            style={{ borderColor: "#8b2317", color: "#8b2317" }}
          >
            <Warning className="size-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <Tabs current={tab} onChange={setTab} data={data} />

        {data && tab === "cohort" && <CohortTab data={data} />}
        {data && tab === "submissions" && <SubmissionsTab data={data} />}
        {data && tab === "attestations" && <AttestationsTab data={data} />}

        {!data && !error && (
          <div className="paper-card p-12 text-center font-serif italic text-muted-foreground">
            <CircleNotch className="size-5 animate-spin mx-auto mb-3 text-primary" />
            Convening the chamber…
          </div>
        )}
      </main>

      {/* Mobile sticky action bar — three buttons, ≥44px each */}
      <div className="md:hidden fixed inset-x-0 bottom-0 z-40 sticky-herald">
        <div className="mx-auto max-w-6xl px-3 py-2 grid grid-cols-3 gap-2">
          <button
            onClick={() => void load()}
            disabled={loading}
            className="touch-target inline-flex flex-col items-center justify-center gap-1 rounded-sm border border-[var(--basalt-border)] bg-[#0f0c09] text-[var(--basalt-foreground)] px-2 py-2 text-[10px] font-mono uppercase tracking-wider disabled:opacity-50"
          >
            {loading ? <CircleNotch className="size-4 animate-spin" /> : <ArrowsClockwise className="size-4" />}
            <span>Refresh</span>
          </button>
          <button
            onClick={triggerEvaluation}
            disabled={busy !== null}
            className="touch-target inline-flex flex-col items-center justify-center gap-1 rounded-sm border border-[var(--gold)] bg-[var(--gold)] text-[#2a2018] px-2 py-2 text-[10px] font-mono uppercase tracking-wider disabled:opacity-50"
          >
            {busy === "trigger" ? <CircleNotch className="size-4 animate-spin" /> : <Cube className="size-4" />}
            <span>{busy === "trigger" ? "Deliberating" : "Deliberate"}</span>
          </button>
          <button
            onClick={publishAttestation}
            disabled={busy !== null}
            className="touch-target inline-flex flex-col items-center justify-center gap-1 rounded-sm border border-primary bg-primary text-primary-foreground px-2 py-2 text-[10px] font-mono uppercase tracking-wider disabled:opacity-50"
          >
            {busy === "publish" ? <CircleNotch className="size-4 animate-spin" /> : <Laurel className="size-4" color="currentColor" />}
            <span>Affix Seal</span>
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Header / nav
// ---------------------------------------------------------------------------

function Nav({ instanceName }: { instanceName: string }) {
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/85 backdrop-blur-md">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 h-14 flex items-center justify-between gap-3">
        <Link href="/" className="touch-target-sm flex items-center gap-2 text-sm font-serif text-muted-foreground hover:text-foreground min-w-0 shrink-0">
          <ArrowLeft className="size-4 shrink-0" />
          <span className="hidden sm:inline">Back to the forum</span>
          <span className="sm:hidden">Back</span>
        </Link>
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          <Laurel className="h-5 w-5 shrink-0" color="#5d2545" />
          <span className="font-display text-xs sm:text-sm tracking-[0.14em] sm:tracking-[0.18em] truncate">
            {instanceName.toUpperCase()}
          </span>
          <MobileDrawer
            title={instanceName.toUpperCase() || "ARENA"}
            eyebrow="INDEX · ARENA"
            links={[
              { label: "Back to the forum", href: "/" },
              { label: "Convene another", href: "/setup" },
              { label: "Source on GitHub", href: "https://github.com/prakhar728/conclave", external: true },
            ]}
          />
        </div>
      </div>
    </header>
  )
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function Tabs({
  current,
  onChange,
  data,
}: {
  current: Tab
  onChange: (t: Tab) => void
  data: DashboardData | null
}) {
  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "cohort", label: "The Lists" },
    { id: "submissions", label: "Submissions", count: data?.submissions.length },
    { id: "attestations", label: "Seals", count: data?.attestations.length },
  ]
  return (
    <div className="border-b border-border overflow-x-auto scrollbar-hide scroll-fade-x -mx-4 sm:mx-0 px-4 sm:px-0">
      <div className="flex items-center gap-1 min-w-max">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => onChange(t.id)}
            className={`touch-target-sm px-4 py-3 text-xs font-mono uppercase tracking-widest border-b-2 transition-colors ${
              current === t.id
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
            {t.count !== undefined && (
              <span className="ml-2 text-muted-foreground">{t.count}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cohort tab — "The Lists"
// ---------------------------------------------------------------------------

function CohortTab({ data }: { data: DashboardData }) {
  const { aggregates, timeline } = data
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Stat label="Cohort size" value={String(aggregates.cohort_size)} sub="gladiators in the lists" />
        <Stat
          label="Last deliberation"
          value={aggregates.last_evaluation_at ? formatRelative(aggregates.last_evaluation_at) : "—"}
          sub={aggregates.last_evaluation_at ? new Date(aggregates.last_evaluation_at).toLocaleString() : "no deliberation yet"}
        />
        <Stat
          label="Name collisions"
          value={String(aggregates.name_collision_pairs)}
          sub="pairs flagged"
        />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Distribution
          title="Faction distribution"
          subtitle="how submissions cluster"
          rows={aggregates.cluster_distribution.map((c) => ({ key: c.label, count: c.count }))}
        />
        <Distribution
          title="Discipline distribution"
          subtitle="alignment across tracks"
          rows={aggregates.track_distribution.map((c) => ({ key: c.track, count: c.count }))}
        />
      </div>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <ClockClockwise className="size-4 text-muted-foreground" />
          <h2 className="bracket-label">LEDGER · DELIBERATIONS</h2>
        </div>
        {timeline.length === 0 ? (
          <div className="paper-card p-10 text-center font-serif italic text-muted-foreground">
            The Conclave has not yet deliberated. Trigger a deliberation or wait for the scheduler tick.
          </div>
        ) : (
          <div className="paper-card divide-y divide-border">
            {timeline.slice().reverse().map((entry) => (
              <div key={entry.run_id} className="px-4 sm:px-5 py-4 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 sm:gap-4">
                <div className="space-y-1 min-w-0">
                  <div className="font-serif text-base">
                    <span className="font-display text-xl text-primary mr-2">
                      {entry.submission_count}
                    </span>
                    <span className="text-muted-foreground italic">submissions judged</span>
                  </div>
                  <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                    {formatRelative(entry.ran_at)} · {new Date(entry.ran_at).toLocaleString()}
                  </div>
                </div>
                {entry.snapshot && entry.snapshot.top_clusters.length > 0 && (
                  <div className="text-xs sm:text-right space-y-0.5 font-mono">
                    <div className="bracket-label">TOP FACTIONS</div>
                    {entry.snapshot.top_clusters.slice(0, 3).map((c) => (
                      <div key={c.label} className="text-muted-foreground">
                        {c.label} <span className="text-primary">·</span> {c.count}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="paper-card p-5">
      <div className="bracket-label mb-3">{label}</div>
      <div className="font-display text-3xl sm:text-4xl md:text-5xl leading-none tabular-nums break-words">{value}</div>
      <div className="gold-rule mt-2 mb-2 w-12" />
      {sub && <div className="font-serif text-sm text-muted-foreground">{sub}</div>}
    </div>
  )
}

function Distribution({
  title,
  subtitle,
  rows,
}: {
  title: string
  subtitle?: string
  rows: { key: string; count: number }[]
}) {
  const max = rows.reduce((m, r) => Math.max(m, r.count), 0) || 1
  return (
    <div className="paper-card p-5 space-y-3">
      <div>
        <div className="font-display text-base uppercase tracking-wider">{title}</div>
        {subtitle && <div className="font-serif italic text-xs text-muted-foreground">{subtitle}</div>}
      </div>
      {rows.length === 0 ? (
        <div className="font-serif italic text-xs text-muted-foreground">No data yet.</div>
      ) : (
        <div className="space-y-2.5">
          {rows.map((r) => (
            <div key={r.key} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="truncate font-serif">{r.key}</span>
                <span className="font-mono text-muted-foreground tabular-nums">{r.count}</span>
              </div>
              <div className="h-1.5 w-full rounded-sm bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary"
                  style={{ width: `${(r.count / max) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Submissions tab
// ---------------------------------------------------------------------------

function SubmissionsTab({ data }: { data: DashboardData }) {
  const { submissions, results } = data
  const resultsById = new Map(results.map((r) => [r.submission_id, r]))

  if (submissions.length === 0) {
    return (
      <div className="paper-card p-12 text-center font-serif italic text-muted-foreground">
        The lists are empty. Share the enclave URL with participants.
      </div>
    )
  }

  return (
    <>
    {/* Mobile — wax-tablet card stack */}
    <ul className="md:hidden space-y-3">
      {submissions.map((s) => {
        const r = resultsById.get(s.submission_id)
        return (
          <li key={s.submission_id} className="wax-tablet p-4 pl-5">
            <div className="flex items-start gap-4">
              <div className="flex-1 min-w-0 space-y-1.5">
                <div className="font-serif text-base leading-snug break-words">
                  {s.idea_title_or_summary || (
                    <span className="italic text-muted-foreground">Untitled submission</span>
                  )}
                </div>
                <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground break-all">
                  {s.submission_id.slice(0, 16)}…
                </div>
              </div>
              {r ? (
                <NoveltyRoundel value={r.novelty_score} />
              ) : (
                <div
                  className="roundel shrink-0"
                  style={{ color: "#8a7a64", background: "var(--background)" }}
                >
                  <span className="roundel-num">—</span>
                  <span className="roundel-pct">PENDING</span>
                </div>
              )}
            </div>
            <div className="mt-3 pt-3 border-t border-dashed border-border grid grid-cols-2 gap-3 text-xs">
              <div className="space-y-0.5">
                <div className="bracket-label !text-[9px]">DISCIPLINE</div>
                <div className="font-serif text-sm leading-tight">
                  {r?.best_fit_track || <span className="text-muted-foreground">—</span>}
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="bracket-label !text-[9px]">FACTION</div>
                <div className="font-mono text-[11px] leading-tight break-words">
                  {r?.cluster_label ? (
                    <>
                      {r.cluster_label}{" "}
                      <span className="text-[var(--gold)]">·</span>{" "}
                      <span className="text-muted-foreground">{r.cluster_size}</span>
                    </>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </div>
              </div>
              <div className="space-y-0.5 col-span-2">
                <div className="bracket-label !text-[9px]">SUBMITTED</div>
                <div className="font-mono text-[11px] text-muted-foreground">
                  {s.submitted_at ? formatRelative(s.submitted_at) : "—"}
                </div>
              </div>
            </div>
          </li>
        )
      })}
    </ul>

    {/* Tablet+ — original table */}
    <div className="paper-card overflow-hidden hidden md:block">
      <div className="overflow-x-auto">
      <table className="w-full text-sm min-w-[720px]">
        <thead className="bg-muted border-b border-border">
          <tr className="text-left bracket-label">
            <th className="px-4 py-3 font-normal">Submission</th>
            <th className="px-4 py-3 font-normal">Title / summary</th>
            <th className="px-4 py-3 font-normal">Novelty</th>
            <th className="px-4 py-3 font-normal">Best discipline</th>
            <th className="px-4 py-3 font-normal">Faction</th>
            <th className="px-4 py-3 font-normal">Submitted</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {submissions.map((s) => {
            const r = resultsById.get(s.submission_id)
            return (
              <tr key={s.submission_id} className="hover:bg-muted/50 transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                  {s.submission_id.slice(0, 12)}…
                </td>
                <td className="px-4 py-3 max-w-[280px] truncate font-serif">
                  {s.idea_title_or_summary || <span className="text-muted-foreground italic">—</span>}
                </td>
                <td className="px-4 py-3">
                  {r ? <NoveltyBadge value={r.novelty_score} /> : <span className="text-muted-foreground italic font-serif text-xs">pending</span>}
                </td>
                <td className="px-4 py-3 font-serif text-sm">
                  {r?.best_fit_track ?? <span className="text-muted-foreground">—</span>}
                </td>
                <td className="px-4 py-3 font-mono text-xs">
                  {r?.cluster_label ? `${r.cluster_label} · ${r.cluster_size}` : <span className="text-muted-foreground">—</span>}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                  {s.submitted_at ? formatRelative(s.submitted_at) : "—"}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      </div>
    </div>
    </>
  )
}

function NoveltyRoundel({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color =
    pct >= 70 ? "#4a6a3a"
    : pct >= 40 ? "#c08a3e"
    : "#8b2317"
  return (
    <div
      className="roundel shrink-0"
      style={{ color, background: "var(--background)" }}
      aria-label={`Novelty ${pct}%`}
    >
      <span className="roundel-num">{pct}</span>
      <span className="roundel-pct">NOVELTY</span>
    </div>
  )
}

function NoveltyBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const tone =
    pct >= 70
      ? { bg: "#4a6a3a", fg: "#f0ead8" }
      : pct >= 40
      ? { bg: "#c08a3e", fg: "#2a2018" }
      : { bg: "#8b2317", fg: "#f0ead8" }
  return (
    <span
      className="inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-mono font-medium tabular-nums"
      style={{ background: tone.bg, color: tone.fg }}
    >
      {pct}%
    </span>
  )
}

// ---------------------------------------------------------------------------
// Attestations tab — "Seals"
// ---------------------------------------------------------------------------

function AttestationsTab({ data }: { data: DashboardData }) {
  const { attestations } = data
  if (attestations.length === 0) {
    return (
      <div className="paper-card p-12 text-center font-serif italic text-muted-foreground">
        No seals yet. They are affixed at end_date or when you click
        &quot;Affix the Seal&quot; above.
      </div>
    )
  }
  return (
    <div className="space-y-4">
      {attestations.slice().reverse().map((a) => (
        <div key={a.report_hash} className="paper-card p-5 space-y-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex items-start gap-4">
              <div className="shrink-0">
                {a.status === "published" ? (
                  <SpqrSeal className="h-14 w-14" />
                ) : (
                  <div className="h-14 w-14 rounded-full border-2 border-dashed border-border flex items-center justify-center text-muted-foreground">
                    ◯
                  </div>
                )}
              </div>
              <div className="space-y-1">
                <StatusPill status={a.status} />
                <div className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  Affixed {formatRelative(a.published_at)} · {a.chain}
                </div>
              </div>
            </div>
            {a.explorer_url && (
              <a
                href={a.explorer_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs font-mono uppercase tracking-wider text-primary hover:underline"
              >
                View on Solana Explorer →
              </a>
            )}
          </div>

          <div className="space-y-1">
            <div className="bracket-label">REPORT HASH (SHA-256)</div>
            <div className="font-mono text-xs break-all bg-muted border border-border rounded-sm px-3 py-2">
              {a.report_hash}
            </div>
          </div>
          {a.tx_sig && (
            <div className="space-y-1">
              <div className="bracket-label">TRANSACTION SIGNATURE</div>
              <div className="font-mono text-xs break-all bg-muted border border-border rounded-sm px-3 py-2">
                {a.tx_sig}
              </div>
            </div>
          )}
          {a.pubkey && (
            <div className="space-y-1">
              <div className="bracket-label">ENCLAVE PUBKEY</div>
              <div className="font-mono text-xs break-all bg-muted border border-border rounded-sm px-3 py-2">
                {a.pubkey}
              </div>
            </div>
          )}
          {a.error && (
            <div className="font-serif italic text-xs" style={{ color: "#8b2317" }}>
              {a.error}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function StatusPill({ status }: { status?: string }) {
  if (status === "published") {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-mono uppercase tracking-wider"
        style={{ background: "#4a6a3a", color: "#f0ead8" }}
      >
        <CheckCircle className="size-3" weight="fill" /> Sealed on-chain
      </span>
    )
  }
  if (status === "local_only") {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-mono uppercase tracking-wider"
        style={{ background: "#c08a3e", color: "#2a2018" }}
      >
        <Warning className="size-3" weight="fill" /> Local only — Solana not configured
      </span>
    )
  }
  if (status === "failed") {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-xs font-mono uppercase tracking-wider"
        style={{ background: "#8b2317", color: "#f0ead8" }}
      >
        <Warning className="size-3" weight="fill" /> Seal broken
      </span>
    )
  }
  return (
    <span className="inline-flex items-center rounded-sm bg-muted px-2 py-0.5 text-xs font-mono uppercase tracking-wider text-muted-foreground">
      {status ?? "unknown"}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Token prompt
// ---------------------------------------------------------------------------

function TokenPrompt({ instanceId, onSubmit }: { instanceId: string; onSubmit: (token: string) => void }) {
  const [value, setValue] = React.useState("")
  return (
    <div className="min-h-screen flex items-center justify-center arena-bg text-foreground p-8">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (value.trim()) onSubmit(value.trim())
        }}
        className="max-w-md w-full space-y-5 paper-card p-8"
      >
        <div className="text-center space-y-2">
          <Laurel className="h-10 w-10 mx-auto" color="#5d2545" />
          <div className="bracket-label">RESTRICTED · IMPERIAL TOKEN</div>
          <h1 className="font-display text-2xl uppercase tracking-wide">Present the seal</h1>
          <p className="font-serif italic text-sm text-muted-foreground">
            Paste the admin_token returned when you convened instance{" "}
            <span className="font-mono not-italic">{instanceId.slice(0, 12)}…</span>.
          </p>
        </div>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="admin token"
          className="touch-target w-full rounded-sm border border-border bg-background px-3 py-2.5 text-base sm:text-sm font-mono focus:border-primary focus:outline-none"
          autoFocus
        />
        <button
          type="submit"
          className="touch-target w-full rounded-sm border border-primary bg-primary px-4 py-3 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          ✦ Enter the Arena
        </button>
        <Link href="/" className="touch-target-sm block text-center text-sm font-serif text-muted-foreground hover:text-foreground">
          Back to the forum
        </Link>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelative(iso: string): string {
  const t = new Date(iso).getTime()
  const diff = Date.now() - t
  if (Number.isNaN(diff)) return "—"
  const sec = Math.round(diff / 1000)
  if (sec < 60) return `${sec}s ago`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const d = Math.round(hr / 24)
  return `${d}d ago`
}
