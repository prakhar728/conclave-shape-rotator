"""Workspace + membership + meeting-share persistence.

CRUD over `workspaces`, `workspace_members`, `meeting_shares` (Alembic 0002).
Mirrors `storage/sqlite.py` style — raw sqlite3, typed columns, JSON only
where the shape is variant.

v1 semantics (per BUILD_DOC §9 + §11):
- Every user has exactly one workspace (auto-named "Personal" at signup).
- Only `role='owner'` is exercised; 'member'/'viewer' are reserved for v1.5.
- `meeting_shares` rows back the 'shared' visibility branch from 1.7.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Optional

from storage.sqlite import _get_conn, _now


def _new_workspace_id() -> str:
    return f"ws_{secrets.token_hex(4)}"


# --- Workspaces ---


def create_workspace(name: str, owner_user_id: str) -> dict:
    """Create a workspace and add owner_user_id as its 'owner' member."""
    conn = _get_conn()
    ws_id = _new_workspace_id()
    now = _now()
    conn.execute(
        "INSERT INTO workspaces (id, name, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ws_id, name, owner_user_id, now, now),
    )
    conn.execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by) "
        "VALUES (?, ?, 'owner', ?, ?)",
        (ws_id, owner_user_id, now, owner_user_id),
    )
    return {
        "id": ws_id,
        "name": name,
        "created_by": owner_user_id,
        "created_at": now,
        "updated_at": now,
    }


def get_workspace(workspace_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, name, created_by, created_at, updated_at FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()
    return dict(row) if row else None


def get_audio_store_default(workspace_id: str) -> bool:
    """Workspace-level store-audio default (Task #30).

    The gMeet invite path falls back to this when no per-meeting choice is made.
    Defaults to True (keep) for any workspace predating the column / missing a row.
    """
    row = _get_conn().execute(
        "SELECT audio_store_default FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()
    if row is None or row["audio_store_default"] is None:
        return True
    return bool(row["audio_store_default"])


def set_audio_store_default(workspace_id: str, enabled: bool) -> None:
    """Set the workspace-level store-audio default."""
    _get_conn().execute(
        "UPDATE workspaces SET audio_store_default = ?, updated_at = ? WHERE id = ?",
        (int(enabled), _now(), workspace_id),
    )


def list_user_workspaces(user_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT w.id, w.name, w.created_by, w.created_at, w.updated_at, m.role "
        "FROM workspaces w "
        "JOIN workspace_members m ON m.workspace_id = w.id "
        "WHERE m.user_id = ? "
        "ORDER BY w.created_at ASC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def ensure_personal_workspace(user_id: str) -> dict:
    """Return the user's "Personal" workspace, creating it if missing.

    Called at the end of OTP verify (1.4) so every new signup lands somewhere.
    Idempotent — re-running on an existing user just returns the existing row.
    """
    existing = list_user_workspaces(user_id)
    if existing:
        return existing[0]
    return create_workspace("Personal", user_id)


# --- Membership ---


def is_member(workspace_id: str, user_id: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
        (workspace_id, user_id),
    ).fetchone()
    return row is not None


def get_member_role(workspace_id: str, user_id: str) -> Optional[str]:
    row = _get_conn().execute(
        "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
        (workspace_id, user_id),
    ).fetchone()
    return row["role"] if row else None


# --- Meeting shares (Phase 1.7 / 2.x consumer; Task #31 per-artifact flags) ---


#: Legacy 2-value permission enum. Retained ONLY for back-compat mapping — the
#: API still accepts these strings for one release (map → flags). Storage moved
#: to three independent booleans in Alembic 0024.
SHARE_SCOPES = ("summary_and_transcript", "summary_only")


@dataclass(frozen=True)
class ShareConfig:
    """Which meeting artifacts a share grants the recipient (Task #31).

    Three independent axes — a meeting can be shared as any subset:
      - ``transcript`` → the raw diarized transcript
      - ``insights``   → summary / signals / entities (the derived view)
      - ``audio``      → the stored recording (Task #30 endpoint)
    """

    transcript: bool
    insights: bool
    audio: bool

    @classmethod
    def default(cls) -> "ShareConfig":
        """Pre-#31 default: summary + transcript, no audio (== the old
        'summary_and_transcript' scope). Preserves 'shared = full access'."""
        return cls(transcript=True, insights=True, audio=False)

    @classmethod
    def from_legacy_scope(cls, scope: str) -> "ShareConfig":
        """Map an old 2-value scope enum onto the three flags.

        summary_and_transcript → (t=1, i=1, a=0); summary_only → (t=0, i=1, a=0).
        """
        if scope == "summary_and_transcript":
            return cls(transcript=True, insights=True, audio=False)
        if scope == "summary_only":
            return cls(transcript=False, insights=True, audio=False)
        raise ValueError(f"scope must be one of {SHARE_SCOPES}, got {scope!r}")

    def to_legacy_scope(self) -> str:
        """Best-effort projection back to the old enum for legacy clients/UI.

        Transcript access ⇒ 'summary_and_transcript', otherwise 'summary_only'.
        Lossy (can't express insights-off or audio in the old vocabulary) — the
        new flags are authoritative; this is a display convenience only.
        """
        return "summary_and_transcript" if self.transcript else "summary_only"


def add_meeting_share(
    session_id: str,
    user_email: str,
    granted_by: str,
    config: Optional[ShareConfig] = None,
    *,
    scope: Optional[str] = None,
) -> None:
    """Grant `user_email` access to a 'shared' meeting at the given artifact flags.

    Pass a :class:`ShareConfig` (preferred) or a legacy ``scope`` string (mapped
    via :meth:`ShareConfig.from_legacy_scope`). With neither, defaults to
    summary + transcript (the pre-#31 grant).

    Idempotent (PK absorbs dups); re-sharing the same email updates the flags,
    so an owner can add/remove any artifact by re-adding the same recipient.
    """
    if config is None:
        config = ShareConfig.from_legacy_scope(scope) if scope is not None else ShareConfig.default()
    conn = _get_conn()
    now = _now()
    # Upsert: ignore if already shared, refresh granted_at + flags otherwise.
    conn.execute(
        "INSERT INTO meeting_shares "
        "(session_id, user_email, granted_by, granted_at, "
        " share_transcript, share_insights, share_audio) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (session_id, user_email) DO UPDATE SET "
        "granted_by = excluded.granted_by, granted_at = excluded.granted_at, "
        "share_transcript = excluded.share_transcript, "
        "share_insights = excluded.share_insights, "
        "share_audio = excluded.share_audio",
        (
            session_id,
            user_email,
            granted_by,
            now,
            int(config.transcript),
            int(config.insights),
            int(config.audio),
        ),
    )


def has_meeting_share(session_id: str, user_email: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM meeting_shares WHERE session_id = ? AND user_email = ?",
        (session_id, user_email),
    ).fetchone()
    return row is not None


def get_meeting_share_scope(session_id: str, user_email: str) -> Optional[ShareConfig]:
    """Return the :class:`ShareConfig` granted to `user_email`, or None if not shared.

    Used by the per-artifact gates to decide which of {transcript, insights,
    audio} a 'shared' recipient may load.
    """
    row = _get_conn().execute(
        "SELECT share_transcript, share_insights, share_audio "
        "FROM meeting_shares WHERE session_id = ? AND user_email = ?",
        (session_id, user_email),
    ).fetchone()
    if row is None:
        return None
    return ShareConfig(
        transcript=bool(row["share_transcript"]),
        insights=bool(row["share_insights"]),
        audio=bool(row["share_audio"]),
    )


def list_meeting_shares(session_id: str) -> list[dict]:
    """Rows for a meeting's shares, each carrying the three artifact flags
    plus a derived legacy ``scope`` string for back-compat display."""
    rows = _get_conn().execute(
        "SELECT session_id, user_email, granted_by, granted_at, user_id, "
        "share_transcript, share_insights, share_audio "
        "FROM meeting_shares WHERE session_id = ? ORDER BY granted_at ASC",
        (session_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["share_transcript"] = bool(d["share_transcript"])
        d["share_insights"] = bool(d["share_insights"])
        d["share_audio"] = bool(d["share_audio"])
        d["scope"] = (
            "summary_and_transcript" if d["share_transcript"] else "summary_only"
        )
        out.append(d)
    return out
