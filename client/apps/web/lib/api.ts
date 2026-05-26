// REST client for the Conclave backend.
// Operator-only endpoints; participants use the agent skill, not this client.

import type {
  Attestation,
  AttestationResponse,
  CohortAggregates,
  CohortTimelineEntry,
  CreateInstanceRequest,
  CreateInstanceResponse,
  GenerateTokenResponse,
  HealthResponse,
  InstanceMeta,
  MeResponse,
  NoveltyResult,
  SkillCard,
  SubmissionMeta,
  SubmitResponse,
} from "./types"

const TEE_URL = process.env.NEXT_PUBLIC_TEE_URL ?? "http://localhost:8000"

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

interface RequestOptions {
  token?: string
  body?: unknown
  method?: "GET" | "POST"
  timeoutMs?: number
}

const DEFAULT_TIMEOUT_MS = 15_000

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (opts.token) headers["Authorization"] = `Bearer ${opts.token}`

  const controller = new AbortController()
  const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  let res: Response
  try {
    res = await fetch(`${TEE_URL}${path}`, {
      method: opts.method ?? (opts.body !== undefined ? "POST" : "GET"),
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError(408, `Request timed out after ${timeoutMs}ms: ${path}`)
    }
    throw e
  } finally {
    clearTimeout(timer)
  }

  if (!res.ok) {
    let detail = ""
    try {
      const errBody = (await res.json()) as { detail?: string }
      detail = errBody.detail ?? ""
    } catch {
      detail = await res.text()
    }
    throw new ApiError(res.status, detail || res.statusText)
  }

  return (await res.json()) as T
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = "ApiError"
  }
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export const api = {
  // Health & metadata (no auth)
  health: () => request<HealthResponse>("/health"),
  attestation: () => request<AttestationResponse>("/attestation"),
  listSkills: () => request<{ skills: SkillCard[] }>("/skills"),
  getSkill: (name: string) => request<SkillCard>(`/skills/${encodeURIComponent(name)}`),
  getInstance: (id: string) => request<InstanceMeta>(`/instances/${encodeURIComponent(id)}`),

  // Operator setup
  createInstance: (body: CreateInstanceRequest) =>
    request<CreateInstanceResponse>("/instances", { body }),

  // Token issuance for participants (agent skill calls /generate-token directly)
  generateToken: (instance_id: string) =>
    request<GenerateTokenResponse>("/generate-token", { body: { instance_id } }),

  // Operator dashboard reads
  me: (token: string) => request<MeResponse>("/me", { token }),
  listSubmissions: (token: string) =>
    request<{ submissions: SubmissionMeta[] }>("/submissions", { token }),
  listResults: (token: string) =>
    request<{ results: NoveltyResult[] }>("/results", { token }),
  getResult: (token: string, submission_id: string) =>
    request<NoveltyResult>(`/results/${encodeURIComponent(submission_id)}`, { token }),
  cohortAggregates: (token: string) =>
    request<CohortAggregates>("/cohort/aggregates", { token }),
  cohortTimeline: (token: string) =>
    request<{ runs: CohortTimelineEntry[] }>("/cohort/timeline", { token }),
  listAttestations: (token: string) =>
    request<{ attestations: Attestation[] }>("/attestations", { token }),

  // Operator actions — pipeline + attestation publish can be slow (model load,
  // LLM calls, Solana RPC), so allow up to 5 minutes before aborting.
  triggerPipeline: (token: string) =>
    request<{ status: string; results_count: number }>("/trigger", {
      token,
      method: "POST",
      timeoutMs: 5 * 60_000,
    }),
  publishAttestation: (token: string) =>
    request<{ latest: Attestation | null }>("/attestations/publish", {
      token,
      method: "POST",
      timeoutMs: 60_000,
    }),

  // Submission (kept for completeness; operator UI typically doesn't call this —
  // participants submit via the agent skill).
  submit: (token: string, payload: { submission_id?: string; idea_text: string; repo_summary?: string }) =>
    request<SubmitResponse>("/submit", { token, body: payload }),
}

export const TEE_BASE_URL = TEE_URL
