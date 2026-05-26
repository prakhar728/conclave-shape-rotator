// Shared types matching the backend Pydantic models.
// Mirrors core/models.py and skills/hackathon_novelty/models.py post-pivot.

export type DisplayHintType = "gauge" | "percentile" | "badge" | "score_table" | "text"

export interface DisplayHint {
  type: DisplayHintType
  label: string
  min?: number
  max?: number
}

export type DisplayMap = Record<string, DisplayHint>

export interface TriggerMode {
  mode: "threshold" | "manual" | "instant"
  description?: string
}

export interface RoleConfig {
  can_trigger?: boolean
  can_view_all?: boolean
  can_view_own?: boolean
}

export interface SkillCard {
  name: string
  description: string
  version: string
  input_schema: Record<string, unknown>
  output_keys: string[]
  user_output_keys: string[]
  config: Record<string, unknown>
  trigger_modes: TriggerMode[]
  roles: { admin?: RoleConfig; user?: RoleConfig }
  setup_prompt: string
  user_display: DisplayMap
}

// POST /instances
export interface TrackConfig {
  name: string
  description_markdown: string
}

export interface CreateInstanceRequest {
  name: string
  end_date: string  // ISO 8601
  evaluation_frequency: string  // "1w" | "3d" | "12h" | "30m" | etc.
  tracks: TrackConfig[]
}

export interface CreateInstanceResponse {
  instance_id: string
  admin_token: string
  enclave_url: string
}

// POST /generate-token
export interface GenerateTokenResponse {
  token: string
  expires_at: string | null
}

// POST /submit
export interface SubmitResponse {
  submission_id: string
  status: "received"
  submissions_count: number
}

// GET /submissions (admin)
export interface SubmissionMeta {
  submission_id: string
  submitted_at: string | null
  has_text: boolean
  has_file: boolean
  has_repo: boolean
  idea_title_or_summary: string
}

// GET /results/{id}
export interface NameCollision {
  other_submission_id: string
  similarity: number
}

export interface NoveltyResult {
  submission_id: string
  novelty_score: number
  aligned?: boolean
  criteria_scores: Record<string, number>
  status: "analyzed" | "duplicate" | "error"
  analysis_depth: "full" | "flagged"
  duplicate_of: string | null
  // Phase 6 additions
  track_alignments: Record<string, number>
  best_fit_track: string | null
  cluster_label: string | null
  cluster_size: number
  confidence: "low" | "high"
  name_collisions: NameCollision[]
  enclave_signature?: string
  attestation_quote?: string
}

// GET /cohort/aggregates
export interface ClusterCount {
  label: string
  count: number
}

export interface TrackCount {
  track: string
  count: number
}

export interface CohortAggregates {
  cohort_size: number
  last_evaluation_at: string | null
  cluster_distribution: ClusterCount[]
  track_distribution: TrackCount[]
  name_collision_pairs: number
}

// GET /cohort/timeline
export interface CohortTimelineEntry {
  run_id: string
  ran_at: string
  submission_count: number
  snapshot: {
    top_clusters: ClusterCount[]
    top_tracks: TrackCount[]
    name_collision_pairs: number
  } | null
}

// GET /attestations
export interface Attestation {
  report_hash: string
  tx_sig: string | null
  chain: string
  published_at: string
  pubkey?: string | null
  explorer_url?: string | null
  status?: "published" | "local_only" | "failed"
  error?: string
}

// GET /attestation
export interface AttestationResponse {
  quote: string
  verify_url: string
}

// GET /health
export interface HealthResponse {
  status: string
  instances: number
  submissions: number
  skills: string[]
}

// GET /me
export interface MeResponse {
  instance_id: string
  role: "admin" | "user"
}

// GET /instances/{id}
export interface InstanceMeta {
  instance_id: string
  skill_name: string
  triggered: boolean
  submissions: number
  threshold: number
}

// Frontend-only: instance metadata persisted in localStorage by the operator UI
export interface StoredInstance {
  instance_id: string
  admin_token: string
  enclave_url: string
  name: string
  created_at: string
}
