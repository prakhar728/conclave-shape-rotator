/**
 * Map a meeting's canonical `origin` (Task #38, emitted by the backend) to a
 * quiet display label + lucide icon for the origin badge.
 *
 * The backend derives `origin` from `(source, platform)` with a legacy
 * bot_invitations fallback (see `infra/meeting_origin.py`); the frontend only
 * renders it. Unknown / missing origins degrade to a neutral "Meeting" label so
 * a card/header never shows a blank or a raw ingest string like "capture".
 */
import {
  Circle,
  Mic,
  Sparkles,
  Upload,
  Video,
  type LucideIcon,
} from "lucide-react";

export type MeetingOriginDisplay = {
  /** Canonical origin key echoed back (useful for data-* hooks / tests). */
  origin: string;
  label: string;
  Icon: LucideIcon;
};

const ORIGINS: Record<string, { label: string; Icon: LucideIcon }> = {
  in_person: { label: "In person", Icon: Mic },
  google_meet: { label: "Google Meet", Icon: Video },
  zoom: { label: "Zoom", Icon: Video },
  teams: { label: "Teams", Icon: Video },
  online: { label: "Online", Icon: Video },
  upload: { label: "Uploaded", Icon: Upload },
  demo: { label: "Demo", Icon: Sparkles },
};

const NEUTRAL: { label: string; Icon: LucideIcon } = {
  label: "Meeting",
  Icon: Circle,
};

/**
 * Resolve the badge display for an origin string. Falls back to a neutral
 * "Meeting" label for `unknown`, missing, or unrecognized values.
 */
export function meetingOrigin(origin?: string | null): MeetingOriginDisplay {
  const key = (origin ?? "").trim().toLowerCase();
  const entry = ORIGINS[key] ?? NEUTRAL;
  return { origin: key || "unknown", ...entry };
}
