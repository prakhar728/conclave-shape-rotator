/**
 * Thin fetch helper for talking to the FastAPI backend.
 *
 * All paths are relative — `/api/...` is rewritten by next.config.ts to
 * the FastAPI port. The httpOnly `conclave_session` cookie rides along
 * automatically; we never have to touch it from JS.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    ...init,
  });
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    // Stale-session self-heal. A 401 on a normal call means the httpOnly
    // `conclave_session` cookie is present but invalid (expired, or the backend
    // restarted). Middleware only checks the cookie EXISTS, so it lets us onto a
    // protected page — and without this, `me()` 401s and the page spins forever.
    // Clear the dead cookie server-side and bounce to /login. Skip the credential
    // endpoints (their 401s are real auth failures, e.g. a wrong OTP) and SSR.
    const credentialPaths = [
      "/api/auth/v1/send-otp",
      "/api/auth/v1/verify-otp",
      "/api/auth/v1/exchange-token",
      "/api/auth/v1/logout",
    ];
    const isCredentialCall = credentialPaths.some((p) => path.startsWith(p));
    if (
      res.status === 401 &&
      !isCredentialCall &&
      typeof window !== "undefined" &&
      !["/login", "/signup"].includes(window.location.pathname)
    ) {
      try {
        await fetch("/api/auth/v1/logout", {
          method: "POST",
          credentials: "same-origin",
        });
      } catch {
        // best-effort — redirect regardless of whether logout succeeds
      }
      const next = encodeURIComponent(
        window.location.pathname + window.location.search,
      );
      window.location.href = `/login?next=${next}`;
      // Halt here so the caller doesn't flash a misleading error mid-redirect.
      await new Promise<never>(() => {});
    }
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    throw new ApiError(
      res.status,
      detail,
      `${res.status} ${typeof detail === "string" ? detail : "Request failed"}`,
    );
  }
  return body as T;
}

// --- Typed endpoints --------------------------------------------------------

export type User = {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  // Config-pinned admin allowlist (CONCLAVE_ADMIN_EMAILS). UI-only hint to reveal
  // admin surfaces; the server re-checks on every admin route.
  is_admin?: boolean;
  // Task #18 — T&C acceptance state. `tnc_needs_acceptance` drives the blocking
  // first-login gate (true until the CURRENT version is accepted).
  tnc_accepted_at?: string | null;
  tnc_version?: string | null;
  tnc_current_version?: string;
  tnc_needs_acceptance?: boolean;
};

export type Workspace = {
  id: string;
  name: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  role?: string;
};

export type MeResponse = {
  user: User;
  workspace: Workspace | null;
};

// --- Attestation (TDX) ------------------------------------------------------
// The backend returns a real hex TDX quote inside a Phala CVM, or a
// "stub_attestation_quote_*" string when not in a TEE (local dev) or when the
// dstack agent is unreachable. The UI must render honestly off that signal.
export type Attestation = { quote: string; verify_url: string };

export const attestation = {
  get: () => apiFetch<Attestation>("/api/attestation"),
};

/** True only for a real hardware quote (not a local/unreachable stub). */
export function isAttested(a: Attestation | null | undefined): boolean {
  return !!a?.quote && !a.quote.startsWith("stub_");
}

export const auth = {
  sendOtp: (email: string) =>
    apiFetch<{ ok: boolean }>("/api/auth/v1/send-otp", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  verifyOtp: (email: string, token: string) =>
    apiFetch<MeResponse>("/api/auth/v1/verify-otp", {
      method: "POST",
      body: JSON.stringify({ email, token }),
    }),
  exchangeToken: (accessToken: string) =>
    apiFetch<MeResponse>("/api/auth/v1/exchange-token", {
      method: "POST",
      body: JSON.stringify({ access_token: accessToken }),
    }),
  logout: () =>
    apiFetch<{ ok: boolean }>("/api/auth/v1/logout", { method: "POST" }),
  me: () => apiFetch<MeResponse>("/api/auth/v1/me"),
};

export type Meeting = {
  session_id: string;
  date: string;
  // Task #39 — full server-stamped ingest timestamp (UTC ISO); null for legacy
  // sessions that only have a date. Drives the time-of-day rendering.
  created_at?: string | null;
  source: string;
  // Task #38 — how the meeting was captured (in_person / google_meet / zoom /
  // teams / online / upload / demo / unknown). Drives the origin badge.
  origin?: string;
  // Task #40 — short meeting title (owner rename or auto). Null for legacy
  // meetings → the UI falls back to the summary's first line.
  title?: string | null;
  summary: string | null;
  is_processing?: boolean;
};

export type OpenQuestion = {
  text: string;
  said_by: string[];
  source_quote: string | null;
  meeting: {
    session_id: string;
    date: string;
    source: string;
    summary: string | null;
  };
};

// Task #32 — workspace multi-membership.
export type WorkspaceMember = {
  user_id: string;
  role: string;
  added_at: string;
  email: string | null;
  display_name: string | null;
};

export type WorkspaceInvite = {
  id: string;
  email: string;
  role: string;
  invited_by: string;
  created_at: string;
};

export const workspaces = {
  list: () =>
    apiFetch<{ workspaces: Workspace[] }>("/api/workspaces"),
  // Task #32 — owner-only membership management.
  listMembers: (id: string) =>
    apiFetch<{ members: WorkspaceMember[]; invites: WorkspaceInvite[] }>(
      `/api/workspaces/${id}/members`,
    ),
  inviteMember: (id: string, email: string, role = "member") =>
    apiFetch<{ invite: WorkspaceInvite }>(`/api/workspaces/${id}/members`, {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),
  removeMember: (id: string, memberUserId: string) =>
    apiFetch<{ ok: boolean; removed: string }>(
      `/api/workspaces/${id}/members/${memberUserId}`,
      { method: "DELETE" },
    ),
  acceptInvite: (token: string) =>
    apiFetch<{ workspace: Workspace; role: string }>(
      `/api/workspaces/accept-invite`,
      { method: "POST", body: JSON.stringify({ token }) },
    ),
  create: (name: string) =>
    apiFetch<{ workspace: Workspace }>("/api/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  get: (id: string) =>
    apiFetch<{ workspace: Workspace; role: string }>(`/api/workspaces/${id}`),
  meetings: (id: string) =>
    apiFetch<{ meetings: Meeting[] }>(`/api/workspaces/${id}/meetings`),
  openQuestions: (id: string) =>
    apiFetch<{ questions: OpenQuestion[] }>(
      `/api/workspaces/${id}/open-questions`,
    ),
  uploadTranscript: (
    id: string,
    params: { filename?: string; text: string; intent?: string },
  ) =>
    apiFetch<{
      session_id: string;
      is_processing: boolean;
      status: "accepted" | "duplicate";
      // present on a "duplicate" — the existing v2's state, so the UI can say
      // "already imported (approved <date>)" vs "continue editing".
      v2_status?: "draft" | "approved" | null;
      approved_at?: string | null;
    }>(`/api/workspaces/${id}/transcripts`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  // Task #12: stash the in-person agenda keyed by the meeting uid, before the
  // mic stream starts. The finalize webhook reads it back and grounds enrichment.
  // 204 No Content on success.
  recordAgenda: (id: string, params: { uid: string; agenda: string }) =>
    apiFetch<void>(`/api/workspaces/${id}/record/agenda`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  // Task #32: stash WHO is recording (server reads the identity from the cookie),
  // keyed by the meeting uid — the finalize webhook uses it as the VFTE identify
  // host. Called at record-start regardless of whether an agenda was typed.
  recordRecorder: (id: string, params: { uid: string }) =>
    apiFetch<void>(`/api/workspaces/${id}/record/recorder`, {
      method: "POST",
      body: JSON.stringify(params),
    }),
  // In-person recording → identified, transcribed meeting. multipart/form-data,
  // so it bypasses apiFetch (which forces a JSON Content-Type); the session
  // cookie still rides along via credentials: "same-origin".
  recordMeeting: async (
    id: string,
    params: { blob: Blob; filename?: string; intent?: string },
  ) => {
    const fd = new FormData();
    fd.append("file", params.blob, params.filename ?? "recording.webm");
    if (params.intent) fd.append("intent", params.intent);
    const res = await fetch(`/api/workspaces/${id}/record`, {
      method: "POST",
      credentials: "same-origin",
      body: fd,
    });
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (!res.ok) {
      const detail =
        typeof body === "object" && body !== null && "detail" in body
          ? (body as { detail: unknown }).detail
          : body;
      throw new ApiError(
        res.status,
        detail,
        `${res.status} ${typeof detail === "string" ? detail : "Recording failed"}`,
      );
    }
    return body as {
      session_id: string;
      is_processing: boolean;
      speakers?: string[];
      status: "accepted" | "duplicate";
    };
  },
};

// --- Meeting detail (legacy /transcripts endpoint, dual-mode in 1.7/1.14) ---

export type Signal = {
  kind: string;
  text: string;
  said_by?: string[];
  about_person?: string[];
  source_quote?: string | null;
};

export type Entity = {
  name: string;
  type: string;
  evidence?: string | null;
};

export type MeetingView = {
  session_id: string;
  date: string;
  // Task #39 — full ingest timestamp (UTC ISO) for time-of-day; null for legacy.
  created_at?: string | null;
  source: string;
  // Task #38 — capture origin (see Meeting.origin).
  origin?: string;
  // Task #40 — short meeting title (owner rename or auto; null → summary-first-line).
  title?: string | null;
  summary: string | null;
  visibility: string;
  owner: string | null;
  resolved_speakers: Record<string, unknown>;
  topics: string[];
  participants: string[] | null;
  signals: Signal[];
  signals_by_kind: {
    action_items: Signal[];
    open_questions: Signal[];
    insights: Signal[];
  };
  // Why insights may be empty: "ok" (ran), "skipped" (no LLM / disabled),
  // "failed" (LLM unreachable), "pending" (still processing).
  enrichment_status?: string;
  // Provenance: non-null iff a per-meeting intent (calendar description or
  // manual focus) was compiled into the insights' <meeting_intent> grounding.
  // Surfaced so a silent break in calendar → insights is visible to the user.
  meeting_intent_version?: string | null;
  entities: Entity[];
  // Phase 2.12 — present only when the viewer is authenticated AND the
  // session has a workspace_id. Lets the frontend gate owner controls
  // without an extra round-trip.
  is_owner?: boolean;
  effective_visibility?: string;
  // Task #32 — sharing state for the owner controls.
  shared_to_workspace?: boolean;
  owner_only?: boolean;
  // P4 — the meeting's workspace, used to POST speaker tags. Present in
  // workspace-mode (authed user + workspace-bound session).
  workspace_id?: string | null;
  // Transcript Saving — whether THIS viewer may load the raw transcript.
  // Drives the transcript panel's state (show vs. "not shared with you").
  can_view_transcript?: boolean;
  // Task #30 — whether this meeting's audio was stored (encrypted at rest).
  // Drives the meeting-page audio player. null/undefined = unknown/legacy.
  store_audio?: boolean | null;
  // Retention (owner-relevant): whether the raw transcript was auto-deleted,
  // and the per-meeting override (null=inherit | 'keep_forever' | '<int>' days).
  raw_transcript_deleted?: boolean;
  retention_override?: string | null;
  // Task #13 — true when a deferred speaker-name confirm diverged the resolved
  // names from the summary's stamp, so a background re-enrich is healing the
  // summary on this open. Drives the reused "Updating insights" badge.
  insights_regenerating?: boolean;
};

// --- Raw transcript (gated surface — Transcript Saving feature) -----------

export type TranscriptSegment = {
  speaker: string;
  speaker_name: string | null;
  // Task #3 — a recognized-but-NOT-yet-consented name to suggest to the host.
  // Present (with speaker_name null) → render a "Proposed: <name>" chip with
  // Confirm/Edit; a proposal is only created when the host submits the tag form.
  proposed_name?: string | null;
  voiceprint_id?: string | null;
  consented?: boolean | null;
  text: string;
  start: number | null;
  end: number | null;
};

export type TranscriptView = {
  session_id: string;
  segment_count: number;
  segments: TranscriptSegment[];
};

// --- P4 speaker tagging (trust handshake) ---------------------------------

export type TagSpeakerResult = {
  label: string;
  voiceprint_id: string;
  status: "confirmed" | "pending" | string;
  name: string | null;
  proposal_id: string | null;
};

export const meetings = {
  get: (sessionId: string) =>
    apiFetch<MeetingView>(`/api/transcripts/sessions/${sessionId}`),
  transcript: (sessionId: string) =>
    apiFetch<TranscriptView>(`/api/transcripts/sessions/${sessionId}/transcript`),
  tagSpeaker: (
    workspaceId: string,
    sessionId: string,
    // Task #15 — `email_transcript` (opt-in) also shares the transcript+insights
    // and emails a magic link to `email` in the same request.
    body: { label: string; name: string; email: string; email_transcript?: boolean },
  ) =>
    apiFetch<TagSpeakerResult>(
      `/api/workspaces/${encodeURIComponent(workspaceId)}/meetings/${encodeURIComponent(
        sessionId,
      )}/tag-speaker`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  // Task #30: the decrypt-on-read audio endpoint. Cookie auth is same-origin, so the
  // returned path can be used directly as an <audio src> — the browser sends the session
  // cookie and the backend decrypts in memory (no plaintext ever written back to disk).
  // Pass start/end (seconds) for a segment clip.
  audioUrl: (sessionId: string, opts?: { start?: number; end?: number }) => {
    const q = new URLSearchParams();
    if (opts?.start != null) q.set("start", String(opts.start));
    if (opts?.end != null) q.set("end", String(opts.end));
    const qs = q.toString();
    return `/api/transcripts/sessions/${encodeURIComponent(sessionId)}/audio${qs ? `?${qs}` : ""}`;
  },
  deleteAudio: (sessionId: string) =>
    apiFetch<{ deleted: boolean; session_id: string }>(
      `/api/transcripts/sessions/${encodeURIComponent(sessionId)}/audio`,
      { method: "DELETE" },
    ),
  // Task #40 — owner rename. A blank title clears the manual override (reverts to
  // the auto title / summary-first-line fallback). Returns the effective title.
  rename: (sessionId: string, title: string) =>
    apiFetch<{ session_id: string; title: string | null; manual: boolean }>(
      `/api/transcripts/sessions/${encodeURIComponent(sessionId)}/title`,
      { method: "PATCH", body: JSON.stringify({ title }) },
    ),
};

// --- Live transcription (SSE) ---------------------------------------------

/**
 * Task #14: the backend live tail (`api/live_routes.py`). SSE stream of each new
 * `live_segments` row (the diart live preview) as it lands. Same-origin, so the
 * session cookie rides along and the URL works directly as an `EventSource` src.
 * The `/recording/[id]` page reads this as its refresh-survivable, second-viewer
 * data source when it does NOT own the low-latency capture WebSocket.
 */
export const live = {
  streamUrl: (nativeId: string) =>
    `/api/meetings/${encodeURIComponent(nativeId)}/live`,
  open: (nativeId: string) => new EventSource(live.streamUrl(nativeId)),
};

// --- Magic links ----------------------------------------------------------

export type MagicLinkLookup = {
  meeting_session_id: string | null;
  user_email: string;
  consumed_at: string | null;
};

export const magicLinks = {
  lookup: (token: string) =>
    apiFetch<MagicLinkLookup>(`/api/magic-links/${encodeURIComponent(token)}`),
  consume: (token: string) =>
    apiFetch<MagicLinkLookup>(`/api/magic-links/${encodeURIComponent(token)}/consume`, {
      method: "POST",
    }),
};

// --- Meeting owner controls (Phase 2.12, 2.13) ----------------------------

export type BotStatus =
  | "requested"
  | "joining"
  | "active"
  | "completed"
  | "failed";

export type BotInviteResp = {
  invitation_id: string;
  meeting_session_id: string;
  status: BotStatus;
};

export type BotStatusResp = {
  invitation_id: string;
  status: BotStatus;
  capture_bot_id: number | null;
  created_at: string;
  completed_at: string | null;
};

export type ActiveInvitation = {
  invitation_id: string;
  session_id: string;
  platform: string;
  status: BotStatus;
  bot_name: string;
  capture_bot_id: number | null;
  created_at: string;
};

export const bots = {
  invite: (params: {
    meet_url_or_code: string;
    workspace_id: string;
    attendee_emails?: string[];
    intent?: string;
  }) =>
    apiFetch<BotInviteResp>("/api/meetings/invite-bot", {
      method: "POST",
      body: JSON.stringify(params),
    }),
  status: (sessionId: string) =>
    apiFetch<BotStatusResp>(`/api/meetings/${sessionId}/bot-status`),
  stop: (sessionId: string) =>
    apiFetch<{ ok: boolean; status: string }>(
      `/api/meetings/${sessionId}/bot`,
      { method: "DELETE" },
    ),
  active: () =>
    apiFetch<{ active: ActiveInvitation[] }>("/api/meetings/active"),
};

// Legacy 2-value enum — kept only for back-compat where old payloads surface it.
// 'summary_and_transcript' lets the recipient open the raw transcript;
// 'summary_only' withholds it (they still get the summary + signals).
export type ShareScope = "summary_and_transcript" | "summary_only";

// Task #31 — a share grants any subset of the three artifacts.
export type ShareConfig = {
  transcript: boolean;
  insights: boolean;
  audio: boolean;
};

export type MeetingShare = {
  email: string;
  granted_at: string;
  // Per-artifact flags (Task #31).
  transcript: boolean;
  insights: boolean;
  audio: boolean;
  // Derived legacy field, still returned by the API for back-compat.
  scope?: ShareScope;
};

export const meetingOwner = {
  setVisibility: (sessionId: string, visibility: "owner-only" | "shared") =>
    apiFetch<{ ok: boolean; visibility: string }>(
      `/api/meetings/${sessionId}/visibility`,
      {
        method: "POST",
        body: JSON.stringify({ visibility }),
      },
    ),
  listShares: (sessionId: string) =>
    apiFetch<{ shares: MeetingShare[] }>(
      `/api/meetings/${sessionId}/shares`,
    ),
  addShare: (sessionId: string, email: string, config: ShareConfig) =>
    apiFetch<{
      ok: boolean;
      email: string;
      transcript: boolean;
      insights: boolean;
      audio: boolean;
      scope: ShareScope;
    }>(`/api/meetings/${sessionId}/shares`, {
      method: "POST",
      body: JSON.stringify({ email, ...config }),
    }),
  // Task #32 — one-click "share with the whole workspace" (every current + future
  // member gets full artifacts). `share: false` revokes it.
  shareWorkspace: (sessionId: string, share: boolean) =>
    apiFetch<{ ok: boolean; shared_to_workspace: boolean }>(
      `/api/meetings/${sessionId}/share-workspace`,
      { method: "POST", body: JSON.stringify({ share }) },
    ),
  // Task #32 — share with ONE specific member (full artifacts, decision B).
  shareMember: (sessionId: string, email: string) =>
    apiFetch<{ ok: boolean; email: string }>(
      `/api/meetings/${sessionId}/share-member`,
      { method: "POST", body: JSON.stringify({ email }) },
    ),
  // Task #32 — the confidential lock: when set, the meeting can't be shared to
  // the workspace/members even by the owner.
  setOwnerOnly: (sessionId: string, locked: boolean) =>
    apiFetch<{ ok: boolean; owner_only: boolean }>(
      `/api/meetings/${sessionId}/owner-only`,
      { method: "POST", body: JSON.stringify({ locked }) },
    ),
  setRetention: (
    sessionId: string,
    body: { mode: "inherit" | "keep_forever" | "days"; days?: number },
  ) =>
    apiFetch<{ ok: boolean; retention_override: string | null }>(
      `/api/meetings/${sessionId}/retention`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),
};

// --- Account settings (Transcript Saving, Phase 2) ------------------------

// retention_days: null = keep transcripts forever; a positive int = auto-delete
// each transcript's RAW text N days after creation (summary + KB are kept).
export type UserSettings = { retention_days: number | null };

export const userSettings = {
  get: () => apiFetch<UserSettings>("/api/users/me/settings"),
  update: (retention_days: number | null) =>
    apiFetch<UserSettings>("/api/users/me/settings", {
      method: "POST",
      body: JSON.stringify({ retention_days }),
    }),
};

// --- KB surface (Phase 3.5b — entities + obligations) -----------------------

export type KBEntity = {
  id: string;
  // fine-grained stored type (kept for back-compat)
  type: "person" | "project" | "topic" | "company" | "tool";
  // OI-7 derived 3-category model — what the UI groups/colors by
  category: "person" | "tech" | "affiliation";
  canonical_name: string;
  definition?: string | null;
  role?: "builder" | "researcher" | "marketing" | "other" | null;
  raw_mentions: string[];
  mention_count: number;
  meeting_count: number;
};

export type KBObligation = {
  id: string;
  session_id: string;
  turn_ids: number[];
  type: "action" | "decision" | "commitment" | "open_question" | "blocker";
  description: string;
  source_quote: string;
  owner_entity_id: string | null;
  owner_raw_text: string | null;
  due_date_raw: string | null;
  status_inferred: "open" | "resolved" | "unclear";
  importance: number | null;
  ingested_at: string;
};

export type KBEntityDetail = {
  entity: Omit<KBEntity, "meeting_count">;
  meetings: {
    session_id: string;
    date: string | null;
    summary: string | null;
    turn_ids: number[];
  }[];
  obligations: KBObligation[];
};

export const kb = {
  entities: (workspaceId: string, params?: { type?: string }) => {
    const q = params?.type ? `?type=${encodeURIComponent(params.type)}` : "";
    return apiFetch<{ entities: KBEntity[] }>(
      `/api/workspaces/${workspaceId}/entities${q}`,
    );
  },
  entity: (workspaceId: string, name: string) =>
    apiFetch<KBEntityDetail>(
      `/api/workspaces/${workspaceId}/entities/${encodeURIComponent(name)}`,
    ),
  obligations: (
    workspaceId: string,
    params?: { type?: string; status?: string; owner_entity_id?: string },
  ) => {
    const search = new URLSearchParams();
    if (params?.type) search.set("type", params.type);
    if (params?.status) search.set("status", params.status);
    if (params?.owner_entity_id)
      search.set("owner_entity_id", params.owner_entity_id);
    const q = search.toString();
    return apiFetch<{ obligations: KBObligation[] }>(
      `/api/workspaces/${workspaceId}/obligations${q ? `?${q}` : ""}`,
    );
  },
};

// --- Hybrid search (Phase 3.5c) ---------------------------------------------

export type SearchResult = {
  chunk_id: string;
  session_id: string;
  score: number;
  snippet: string;
  context_header: string | null;
  turn_ids: number[];
  meeting: { session_id: string; date: string | null; summary: string | null };
};

export const search = {
  query: (workspaceId: string, query: string, topK = 20) =>
    apiFetch<{ results: SearchResult[] }>(
      `/api/workspaces/${workspaceId}/search`,
      { method: "POST", body: JSON.stringify({ query, top_k: topK }) },
    ),
};

// --- /ask — grounded answers (v1.5, flag-gated server-side) -----------------

export type AskCitation = {
  kind: "chunk" | "obligation";
  id: string;
  session_id: string;
};

export type AskResponse = {
  answer: string;
  citations: AskCitation[];
  grounded: boolean;
};

export const ask = {
  question: (workspaceId: string, question: string) =>
    apiFetch<AskResponse>(`/api/workspaces/${workspaceId}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
};

// --- Google Calendar --------------------------------------------------------

export type CalendarStatus =
  | { connected: false }
  | {
      connected: true;
      scopes: string;
      connected_at: string;
      // workspace_id when "record all my meetings" is on, else null.
      auto_record_all: string | null;
    };

export type CalendarEvent = {
  id: string;
  title: string;
  start: string | null;
  end: string | null;
  hangout_link: string | null;
  auto_record: boolean;
};

export type AutoRecordResp = {
  ok: boolean;
  event_id: string;
  enabled: boolean;
  meet_code: string | null;
};

export const calendar = {
  status: () => apiFetch<CalendarStatus>("/api/calendar/status"),
  connect: () => apiFetch<{ auth_url: string }>("/api/calendar/connect"),
  disconnect: () =>
    apiFetch<{ ok: boolean }>("/api/calendar/disconnect", { method: "POST" }),
  events: (windowHours = 168) =>
    apiFetch<{ events: CalendarEvent[] }>(
      `/api/calendar/events?window_hours=${windowHours}`,
    ),
  setAutoRecord: (eventId: string, enabled: boolean, workspaceId: string) =>
    apiFetch<AutoRecordResp>(
      `/api/calendar/events/${encodeURIComponent(eventId)}/auto-record`,
      {
        method: "POST",
        body: JSON.stringify({ enabled, workspace_id: workspaceId }),
      },
    ),
  setAutoRecordAll: (enabled: boolean, workspaceId: string) =>
    apiFetch<{ ok: boolean; auto_record_all: string | null }>(
      "/api/calendar/auto-record-all",
      {
        method: "POST",
        body: JSON.stringify({ enabled, workspace_id: workspaceId }),
      },
    ),
};

// --- Transcript refinement (the v2 editor) ----------------------------------

export type V2Span = {
  segment_id: number;
  token_start: number;
  token_end: number;
};

export type V2Annotation = {
  span: V2Span;
  surface: string;
  state: "known" | "candidate" | "oov";
  type: string | null;
  source: "nlp" | "correction" | "user";
  confidence: number | null;
};

export type V2Segment = {
  segment_id: number;
  speaker_label: string;
  speaker_name: string | null;
  tokens: string[];
};

export type V2Draft = {
  session_id: string;
  status: "draft" | "approved";
  approved_at: string | null;
  insights_stale: boolean;
  segments: V2Segment[];
  annotations: V2Annotation[];
};

export type V2Debug = {
  status: string;
  insights_stale: boolean;
  segments: { speaker: string; text: string }[];
  annotations: { surface: string; state: string; type: string | null; source: string }[];
  vocab: { surface: string; type: string | null; provenance: string | null }[];
  recent_corrections: { count: number; approved_at: string | null }[];
  trust_state: string;
  entity_count: number | null;
  fact_count: number | null;
};

const sess = (id: string) => `/api/transcripts/sessions/${encodeURIComponent(id)}`;

export const refine = {
  getDraft: (sessionId: string) => apiFetch<V2Draft>(`${sess(sessionId)}/v2`),

  editToken: (sessionId: string, segmentId: number, tokenIdx: number, newText: string) =>
    apiFetch<{ decision: "promote" | "text"; v2: V2Draft }>(`${sess(sessionId)}/v2/edit-token`, {
      method: "POST",
      body: JSON.stringify({ segment_id: segmentId, token_idx: tokenIdx, new_text: newText }),
    }),

  tagEntity: (
    sessionId: string,
    body: { segment_id: number; token_start: number; token_end: number; surface: string; type: string | null },
  ) =>
    apiFetch<{ v2: V2Draft }>(`${sess(sessionId)}/v2/tag-entity`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  assignSpeaker: (sessionId: string, segmentId: number, name: string | null) =>
    apiFetch<{ v2: V2Draft }>(`${sess(sessionId)}/v2/assign-speaker`, {
      method: "POST",
      body: JSON.stringify({ segment_id: segmentId, name }),
    }),

  approve: (sessionId: string) =>
    apiFetch<{ session_id: string; status: string }>(`${sess(sessionId)}/approve`, {
      method: "POST",
    }),

  speakerSuggestions: (sessionId: string) =>
    apiFetch<{ speakers: string[] }>(`${sess(sessionId)}/suggestions/speakers`),

  vocabSuggestions: (prefix: string) =>
    apiFetch<{ vocab: string[] }>(`/api/transcripts/suggestions/vocab?prefix=${encodeURIComponent(prefix)}`),

  debug: (sessionId: string) => apiFetch<V2Debug>(`${sess(sessionId)}/debug`),
};

// --- Task #20: contribute a meeting to Shape Rotator OS ----------------------

export type ShapeContribResult = {
  inbox: {
    ok: boolean;
    status: "ok" | "dry_run" | "unconfigured" | "network" | "forbidden" | "rejected";
    parts: number;
    http_statuses: number[];
    detail?: string;
  };
};

export const shapeContrib = {
  // Host-only; runs Arm 1 (approved v2 → Shape OS context_submissions inbox).
  contribute: (sessionId: string) =>
    apiFetch<ShapeContribResult>(
      `/api/meetings/${encodeURIComponent(sessionId)}/contribute-shapeos`,
      { method: "POST" },
    ),
};

// --- Feedback (Task #19) ----------------------------------------------------

export type FeedbackCategory = "feature" | "bug" | "other";

export type FeedbackInput = {
  category: FeedbackCategory;
  body: string;
  page_context?: string | null;
  workspace_id?: string | null;
};

export type FeedbackItem = {
  id: string;
  user_id: string | null;
  user_email: string;
  workspace_id: string | null;
  category: FeedbackCategory;
  body: string;
  page_context: string | null;
  created_at: string;
};

export type FeedbackList = {
  items: FeedbackItem[];
  total: number;
  limit: number;
  offset: number;
};

export const feedback = {
  submit: (input: FeedbackInput) =>
    apiFetch<{ id: string; created_at: string }>("/api/feedback", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  // Admin-only (server-gated by CONCLAVE_ADMIN_EMAILS).
  list: (params?: { limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.offset != null) q.set("offset", String(params.offset));
    const qs = q.toString();
    return apiFetch<FeedbackList>(`/api/feedback${qs ? `?${qs}` : ""}`);
  },
};

// --- Terms & Conditions + Data export (Task #18) ---------------------------
// (Appended block — keep both if a parallel branch also appends here.)

export type TncStatus = {
  version: string;
  text: string;
  accepted_at: string | null;
  accepted_version: string | null;
  needs_acceptance: boolean;
};

export const tnc = {
  get: () => apiFetch<TncStatus>("/api/users/me/tnc"),
  accept: (version: string) =>
    apiFetch<TncStatus>("/api/users/me/tnc/accept", {
      method: "POST",
      body: JSON.stringify({ version }),
    }),
};

export type ExportJob = {
  export_id: string;
  status: "pending" | "processing" | "done" | "failed";
  include_audio: boolean;
  error?: string | null;
};

// The export endpoints return a ZIP (not JSON), so downloads use a plain
// same-origin navigation (the session cookie rides along) rather than apiFetch.
export const dataExport = {
  // Synchronous, no-audio dump — navigate the browser to trigger the download.
  downloadUrl: () => "/api/users/me/export",
  // Async (audio-on) build → poll → download.
  startJob: (include_audio: boolean) =>
    apiFetch<ExportJob>("/api/users/me/export/jobs", {
      method: "POST",
      body: JSON.stringify({ include_audio }),
    }),
  jobStatus: (exportId: string) =>
    apiFetch<ExportJob>(`/api/users/me/export/jobs/${exportId}`),
  jobDownloadUrl: (exportId: string) =>
    `/api/users/me/export/jobs/${exportId}/download`,
};
