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
  source: string;
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

export const workspaces = {
  list: () =>
    apiFetch<{ workspaces: Workspace[] }>("/api/workspaces"),
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
    }>(`/api/workspaces/${id}/transcripts`, {
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
  source: string;
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
  entities: Entity[];
  // Phase 2.12 — present only when the viewer is authenticated AND the
  // session has a workspace_id. Lets the frontend gate owner controls
  // without an extra round-trip.
  is_owner?: boolean;
  effective_visibility?: string;
  // P4 — the meeting's workspace, used to POST speaker tags. Present in
  // workspace-mode (authed user + workspace-bound session).
  workspace_id?: string | null;
  // Transcript Saving — whether THIS viewer may load the raw transcript.
  // Drives the transcript panel's state (show vs. "not shared with you").
  can_view_transcript?: boolean;
  // Retention (owner-relevant): whether the raw transcript was auto-deleted,
  // and the per-meeting override (null=inherit | 'keep_forever' | '<int>' days).
  raw_transcript_deleted?: boolean;
  retention_override?: string | null;
};

// --- Raw transcript (gated surface — Transcript Saving feature) -----------

export type TranscriptSegment = {
  speaker: string;
  speaker_name: string | null;
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
    body: { label: string; name: string; email: string },
  ) =>
    apiFetch<TagSpeakerResult>(
      `/api/workspaces/${encodeURIComponent(workspaceId)}/meetings/${encodeURIComponent(
        sessionId,
      )}/tag-speaker`,
      { method: "POST", body: JSON.stringify(body) },
    ),
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
  recato_bot_id: number | null;
  created_at: string;
  completed_at: string | null;
};

export type ActiveInvitation = {
  invitation_id: string;
  session_id: string;
  platform: string;
  status: BotStatus;
  bot_name: string;
  recato_bot_id: number | null;
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

// 'summary_and_transcript' lets the recipient open the raw transcript;
// 'summary_only' withholds it (they still get the summary + signals).
export type ShareScope = "summary_and_transcript" | "summary_only";

export type MeetingShare = {
  email: string;
  granted_at: string;
  scope: ShareScope;
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
  addShare: (sessionId: string, email: string, scope: ShareScope) =>
    apiFetch<{ ok: boolean; email: string; scope: ShareScope }>(
      `/api/meetings/${sessionId}/shares`,
      {
        method: "POST",
        body: JSON.stringify({ email, scope }),
      },
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
  type: "person" | "project" | "topic" | "company" | "tool";
  canonical_name: string;
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
