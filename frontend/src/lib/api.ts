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
  logout: () =>
    apiFetch<{ ok: boolean }>("/api/auth/v1/logout", { method: "POST" }),
  me: () => apiFetch<MeResponse>("/api/auth/v1/me"),
};

export type Meeting = {
  session_id: string;
  date: string;
  source: string;
  summary: string | null;
};

export const workspaces = {
  list: () =>
    apiFetch<{ workspaces: Workspace[] }>("/api/workspaces"),
  get: (id: string) =>
    apiFetch<{ workspace: Workspace; role: string }>(`/api/workspaces/${id}`),
  meetings: (id: string) =>
    apiFetch<{ meetings: Meeting[] }>(`/api/workspaces/${id}/meetings`),
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
};

export const meetings = {
  get: (sessionId: string) =>
    apiFetch<MeetingView>(`/api/transcripts/sessions/${sessionId}`),
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

export type MeetingShare = { email: string; granted_at: string };

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
  addShare: (sessionId: string, email: string) =>
    apiFetch<{ ok: boolean; email: string }>(
      `/api/meetings/${sessionId}/shares`,
      {
        method: "POST",
        body: JSON.stringify({ email }),
      },
    ),
};
