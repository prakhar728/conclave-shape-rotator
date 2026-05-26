"use client"

import * as React from "react"
import Link from "next/link"
import {
  ArrowLeft,
  Plus,
  X,
  Copy,
  Check,
  CircleNotch,
} from "@phosphor-icons/react"

import { AttestationWidget } from "@/components/attestation-widget"
import { Laurel } from "@/components/seal-marks"
import { MobileDrawer } from "@/components/mobile-drawer"
import { api, ApiError } from "@/lib/api"
import { FRONTIER_PRESET } from "@/lib/presets/frontier"
import type { CreateInstanceResponse, TrackConfig } from "@/lib/types"

const FREQUENCY_OPTIONS = [
  { value: "30m", label: "Every 30 min (testing)" },
  { value: "1h", label: "Every hour" },
  { value: "6h", label: "Every 6 hours" },
  { value: "1d", label: "Daily" },
  { value: "3d", label: "Every 3 days" },
  { value: "1w", label: "Weekly" },
  { value: "2w", label: "Every 2 weeks" },
]

const INSTALL_COMMAND = "npx skills add prakhar728/conclave"

interface FormState {
  name: string
  end_date: string
  evaluation_frequency: string
  tracks: TrackConfig[]
}

function blankTrack(): TrackConfig {
  return { name: "", description_markdown: "" }
}

function defaultEndDate(): string {
  const d = new Date(Date.now() + 14 * 24 * 60 * 60 * 1000)
  d.setSeconds(0, 0)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function SetupPage() {
  const [verified, setVerified] = React.useState(false)
  const [form, setForm] = React.useState<FormState>(() => ({
    name: "",
    end_date: defaultEndDate(),
    evaluation_frequency: "1d",
    tracks: [{ name: "", description_markdown: "" }],
  }))
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [result, setResult] = React.useState<CreateInstanceResponse | null>(null)

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((s) => ({ ...s, [key]: value }))
  }

  function setTrack(i: number, patch: Partial<TrackConfig>) {
    setForm((s) => ({
      ...s,
      tracks: s.tracks.map((t, idx) => (idx === i ? { ...t, ...patch } : t)),
    }))
  }

  function addTrack() {
    setForm((s) => ({ ...s, tracks: [...s.tracks, blankTrack()] }))
  }

  function removeTrack(i: number) {
    setForm((s) => ({ ...s, tracks: s.tracks.filter((_, idx) => idx !== i) }))
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    if (!form.name.trim()) return setError("Hackathon name is required")
    if (!form.end_date) return setError("End date is required")
    if (form.tracks.length === 0) return setError("At least one track is required")
    for (const t of form.tracks) {
      if (!t.name.trim()) return setError("Every track needs a name")
      if (!t.description_markdown.trim()) return setError("Every track needs a description")
    }

    const endIso = new Date(form.end_date).toISOString()
    if (new Date(endIso) <= new Date()) return setError("End date must be in the future")

    setSubmitting(true)
    try {
      const resp = await api.createInstance({
        name: form.name.trim(),
        end_date: endIso,
        evaluation_frequency: form.evaluation_frequency,
        tracks: form.tracks,
      })
      setResult(resp)
      try {
        const stored = JSON.parse(localStorage.getItem("conclave.instances") || "[]") as unknown[]
        localStorage.setItem(
          "conclave.instances",
          JSON.stringify([
            ...stored,
            {
              instance_id: resp.instance_id,
              admin_token: resp.admin_token,
              enclave_url: resp.enclave_url,
              name: form.name.trim(),
              created_at: new Date().toISOString(),
            },
          ]),
        )
      } catch {
        // localStorage failure is non-fatal
      }
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  if (result) {
    return <SuccessView result={result} hackathonName={form.name} />
  }

  return (
    <div className="min-h-screen arena-bg text-foreground">
      <Nav />
      <main className="mx-auto max-w-3xl px-4 sm:px-6 py-8 sm:py-12 space-y-8 sm:space-y-10">
        <header className="space-y-3">
          <div className="bracket-label">FOR EDITORS · ESTABLISH AN INSTANCE</div>
          <h1 className="font-display text-3xl sm:text-4xl md:text-5xl tracking-wide leading-tight">
            ENTER THE LISTS
          </h1>
          <p className="font-serif text-sm sm:text-base text-muted-foreground leading-snug max-w-2xl">
            Convene a Conclave for your hackathon. The enclave scores submissions
            confidentially. You will receive a unique URL to share with the lists
            and an admin token for the dashboard.
          </p>
        </header>

        {!verified ? (
          <section className="paper-card p-6 space-y-4">
            <div className="flex items-center gap-3">
              <Laurel className="h-6 w-6" color="#5d2545" />
              <div className="font-display text-lg uppercase tracking-wider">
                First, verify the seal
              </div>
            </div>
            <p className="font-serif text-sm text-muted-foreground leading-snug">
              Before you configure anything, confirm this enclave runs the
              expected code. The form unlocks once the seal is verified.
            </p>
            <AttestationWidget onVerified={() => setVerified(true)} />
            {process.env.NEXT_PUBLIC_SHOW_DEV_TOOLS === "1" && (
              <button
                type="button"
                onClick={() => setVerified(true)}
                className="rounded-sm border border-dashed border-primary/50 bg-primary/5 px-3 py-1.5 text-xs font-mono uppercase tracking-wider text-primary hover:bg-primary/10 transition-colors"
              >
                Dev · skip seal verification
              </button>
            )}
          </section>
        ) : (
          <form onSubmit={submit} className="space-y-10">
            {process.env.NEXT_PUBLIC_SHOW_DEV_TOOLS === "1" && (
              <button
                type="button"
                onClick={() =>
                  setForm({
                    name: FRONTIER_PRESET.name,
                    end_date: FRONTIER_PRESET.end_date,
                    evaluation_frequency: FRONTIER_PRESET.evaluation_frequency,
                    tracks: FRONTIER_PRESET.tracks.map((t) => ({ ...t })),
                  })
                }
                className="rounded-sm border border-dashed border-primary/50 bg-primary/5 px-3 py-1.5 text-xs font-mono uppercase tracking-wider text-primary hover:bg-primary/10 transition-colors"
              >
                Dev · prefill Solana Frontier 2026
              </button>
            )}

            <Section
              title="The Hackathon"
              hint="Names and timing for the games."
            >
              <Field
                label="Display name"
                hint="Shown in the operator dashboard."
              >
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  placeholder="Frontier 2026"
                  className="touch-target w-full rounded-sm border border-border bg-background px-3 py-2.5 text-base sm:text-sm font-mono focus:border-primary focus:outline-none"
                />
              </Field>

              <Field
                label="End date"
                hint="When the hackathon closes. Final attestation publishes after this."
              >
                <input
                  type="datetime-local"
                  required
                  value={form.end_date}
                  onChange={(e) => update("end_date", e.target.value)}
                  className="touch-target w-full rounded-sm border border-border bg-background px-3 py-2.5 text-base sm:text-sm font-mono focus:border-primary focus:outline-none"
                />
              </Field>

              <Field
                label="Deliberation cadence"
                hint="How often the Conclave scores the accumulated cohort."
              >
                <select
                  value={form.evaluation_frequency}
                  onChange={(e) => update("evaluation_frequency", e.target.value)}
                  className="touch-target w-full rounded-sm border border-border bg-background px-3 py-2.5 text-base sm:text-sm font-mono focus:border-primary focus:outline-none"
                >
                  {FREQUENCY_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </Field>
            </Section>

            <Section
              title="The Disciplines"
              hint="Each submission is scored for alignment against every track. Markdown is supported in descriptions."
            >
              <div className="space-y-3">
                {form.tracks.map((t, i) => (
                  <TrackEditor
                    key={i}
                    track={t}
                    onChange={(patch) => setTrack(i, patch)}
                    onRemove={form.tracks.length > 1 ? () => removeTrack(i) : undefined}
                    index={i}
                  />
                ))}
              </div>
              <button
                type="button"
                onClick={addTrack}
                className="touch-target inline-flex items-center gap-1.5 rounded-sm border border-dashed border-border bg-background px-4 py-2.5 text-xs font-mono uppercase tracking-wider hover:border-primary hover:text-primary transition-colors"
              >
                <Plus className="size-3.5" />
                Add discipline
              </button>
            </Section>

            {error && (
              <div className="rounded-sm border border-blood bg-background px-4 py-3 text-sm font-serif italic" style={{ borderColor: "#8b2317", color: "#8b2317" }}>
                {error}
              </div>
            )}

            <div className="flex items-center gap-3 pt-2">
              <button
                type="submit"
                disabled={submitting}
                className="touch-target inline-flex w-full sm:w-auto items-center justify-center gap-2 rounded-sm border border-primary bg-primary px-5 py-3 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {submitting && <CircleNotch className="size-4 animate-spin" />}
                {submitting ? "Convening…" : "✦ Convene the Conclave"}
              </button>
              <Link href="/" className="touch-target-sm inline-flex items-center text-sm font-serif text-muted-foreground hover:text-foreground">
                Cancel
              </Link>
            </div>
          </form>
        )}
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function Nav() {
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/85 backdrop-blur-md">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 h-14 flex items-center justify-between gap-3">
        <Link href="/" className="touch-target-sm flex items-center gap-2 text-sm font-serif text-muted-foreground hover:text-foreground min-w-0">
          <ArrowLeft className="size-4 shrink-0" />
          <span className="truncate"><span className="hidden sm:inline">Back to the forum</span><span className="sm:hidden">Back</span></span>
        </Link>
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          <Laurel className="h-5 w-5 shrink-0" color="#5d2545" />
          <span className="font-display text-sm tracking-[0.18em] truncate">CONCLAVE</span>
          <span className="hidden sm:inline font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            / setup
          </span>
          <MobileDrawer
            title="CONCLAVE"
            eyebrow="INDEX · SETUP"
            links={[
              { label: "Back to the forum", href: "/" },
              { label: "Source on GitHub", href: "https://github.com/prakhar728/conclave", external: true },
            ]}
          />
        </div>
      </div>
    </header>
  )
}

function Section({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-4">
      <div className="space-y-1">
        <h2 className="font-display text-2xl uppercase tracking-wide">{title}</h2>
        {hint && <p className="font-serif italic text-sm text-muted-foreground">{hint}</p>}
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <label className="block space-y-1.5">
      <div>
        <div className="font-serif text-sm font-semibold">{label}</div>
        {hint && <div className="font-serif italic text-xs text-muted-foreground">{hint}</div>}
      </div>
      {children}
    </label>
  )
}

function TrackEditor({
  track,
  onChange,
  onRemove,
  index,
}: {
  track: TrackConfig
  onChange: (patch: Partial<TrackConfig>) => void
  onRemove?: () => void
  index: number
}) {
  return (
    <div className="plaque p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="bracket-label">DISCIPLINE · {String(index + 1).padStart(2, "0")}</div>
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            className="touch-target inline-flex items-center justify-center w-11 h-11 -mr-2 rounded-sm text-muted-foreground hover:text-[var(--blood)] hover:bg-muted/60 transition-colors"
            aria-label="Remove track"
          >
            <X className="size-4" />
          </button>
        )}
      </div>
      <input
        type="text"
        required
        value={track.name}
        onChange={(e) => onChange({ name: e.target.value })}
        placeholder="DeFi"
        className="touch-target w-full rounded-sm border border-border bg-background px-3 py-2.5 text-base sm:text-sm font-mono focus:border-primary focus:outline-none"
      />
      <textarea
        required
        value={track.description_markdown}
        onChange={(e) => onChange({ description_markdown: e.target.value })}
        placeholder="Markdown description of what this discipline is about, evaluation criteria, prizes, themes..."
        rows={4}
        className="w-full rounded-sm border border-border bg-background px-3 py-2.5 text-base sm:text-sm font-mono focus:border-primary focus:outline-none"
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Success view
// ---------------------------------------------------------------------------

function SuccessView({
  result,
  hackathonName,
}: {
  result: CreateInstanceResponse
  hackathonName: string
}) {
  return (
    <div className="min-h-screen arena-bg text-foreground">
      <Nav />
      <main className="mx-auto max-w-3xl px-4 sm:px-6 py-8 sm:py-12 space-y-8 sm:space-y-10">
        <div className="text-center space-y-3">
          <div className="bracket-label">SEALED · INSTANCE ESTABLISHED</div>
          <Laurel className="h-12 w-12 mx-auto laurel-grow" color="#5d2545" />
          <h1 className="font-display text-2xl sm:text-3xl md:text-4xl tracking-wide uppercase mt-4 break-words">
            {hackathonName} is convened
          </h1>
          <p className="font-serif italic text-sm sm:text-base text-muted-foreground max-w-xl mx-auto">
            Share the participant URL with the lists. Bookmark the dashboard
            URL with your admin token — guard it like the imperial seal itself.
          </p>
        </div>

        <SuccessRow
          label="The herald's message"
          hint="Copy and paste this into your hackathon's Discord or announcements."
          value={`Install the Conclave skill in your coding agent:\n${INSTALL_COMMAND}\nEnclave URL: ${result.enclave_url}\nInstance ID: ${result.instance_id}`}
          multiline
        />

        <SuccessRow label="Enclave URL" value={result.enclave_url} />
        <SuccessRow label="Instance ID" value={result.instance_id} />
        <SuccessRow
          label="Admin token (the seal — do not share)"
          value={result.admin_token}
          mask
        />

        <div className="pt-4 flex flex-col sm:flex-row sm:flex-wrap items-stretch sm:items-center gap-3">
          <Link
            href={`/dashboard/${result.instance_id}`}
            className="touch-target inline-flex items-center justify-center gap-2 rounded-sm border border-primary bg-primary px-5 py-3 text-xs font-mono uppercase tracking-wider text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            ✦ Enter the Arena
          </Link>
          <Link href="/" className="touch-target-sm inline-flex items-center justify-center text-sm font-serif text-muted-foreground hover:text-foreground">
            Back to the forum
          </Link>
        </div>
      </main>
    </div>
  )
}

function SuccessRow({
  label,
  hint,
  value,
  multiline,
  mask,
}: {
  label: string
  hint?: string
  value: string
  multiline?: boolean
  mask?: boolean
}) {
  const [copied, setCopied] = React.useState(false)
  const [revealed, setRevealed] = React.useState(!mask)
  async function copy() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1200)
  }
  return (
    <div className="space-y-2">
      <div>
        <div className="font-serif text-sm font-semibold">{label}</div>
        {hint && <div className="font-serif italic text-xs text-muted-foreground">{hint}</div>}
      </div>
      <div className="flex items-stretch gap-2 min-w-0">
        {multiline ? (
          <pre
            className="flex-1 min-w-0 rounded-sm border px-4 py-3 font-mono text-xs whitespace-pre-wrap break-all"
            style={{ background: "var(--basalt)", color: "var(--basalt-foreground)", borderColor: "var(--basalt-border)" }}
          >
            {value}
          </pre>
        ) : (
          <div
            className="flex-1 min-w-0 rounded-sm border px-4 py-3 font-mono text-xs truncate"
            style={{ background: "var(--basalt)", color: "var(--basalt-foreground)", borderColor: "var(--basalt-border)" }}
          >
            {revealed ? value : "•".repeat(Math.min(value.length, 32))}
          </div>
        )}
        <button
          onClick={copy}
          className="touch-target inline-flex items-center justify-center min-w-[44px] rounded-sm border border-border bg-background px-3 hover:border-primary transition-colors"
          aria-label="Copy"
        >
          {copied ? <Check className="size-4 text-primary" weight="bold" /> : <Copy className="size-4" />}
        </button>
        {mask && (
          <button
            onClick={() => setRevealed((r) => !r)}
            className="touch-target inline-flex items-center justify-center rounded-sm border border-border bg-background px-3 text-xs font-mono uppercase tracking-wider hover:border-primary transition-colors"
          >
            {revealed ? "Hide" : "Reveal"}
          </button>
        )}
      </div>
    </div>
  )
}
