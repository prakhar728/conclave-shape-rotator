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


WORKSPACE_TYPES = ("personal", "team")


class PersonalWorkspaceInviteError(Exception):
    """Raised on any attempt to invite/add a second member to a `personal` workspace.
    Personal workspaces are solo by design; collaboration happens in `team` workspaces."""


def create_workspace(name: str, owner_user_id: str, type: str = "team") -> dict:
    """Create a workspace and add owner_user_id as its 'owner' member.

    `type` is 'team' (default — invite-gated, many members) or 'personal'
    (auto-provisioned on first login, solo, NON-invitable — see add_workspace_member)."""
    if type not in WORKSPACE_TYPES:
        raise ValueError(f"workspace type must be one of {WORKSPACE_TYPES}, got {type!r}")
    conn = _get_conn()
    ws_id = _new_workspace_id()
    now = _now()
    conn.execute(
        "INSERT INTO workspaces (id, name, type, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ws_id, name, type, owner_user_id, now, now),
    )
    conn.execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by) "
        "VALUES (?, ?, 'owner', ?, ?)",
        (ws_id, owner_user_id, now, owner_user_id),
    )
    return {
        "id": ws_id,
        "name": name,
        "type": type,
        "created_by": owner_user_id,
        "created_at": now,
        "updated_at": now,
    }


def get_workspace(workspace_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, name, type, created_by, created_at, updated_at FROM workspaces WHERE id = ?",
        (workspace_id,),
    ).fetchone()
    return dict(row) if row else None


def is_personal(workspace_id: str) -> bool:
    """True for a solo `personal` workspace (invites blocked)."""
    row = _get_conn().execute(
        "SELECT type FROM workspaces WHERE id = ?", (workspace_id,)
    ).fetchone()
    return bool(row) and row["type"] == "personal"


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
        "SELECT w.id, w.name, w.type, w.created_by, w.created_at, w.updated_at, m.role "
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
    return create_workspace("Personal", user_id, type="personal")


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


#: Roles in v1 of multi-membership (Task #32). `viewer` is reserved for v1.5.
WORKSPACE_ROLES = ("owner", "member")


def is_owner(workspace_id: str, user_id: str) -> bool:
    """True iff `user_id` is the/an owner of the workspace — the manage gate.

    Owner-only manages membership (invite / remove / list) and per-meeting sharing
    (§0b-C). Members can see-what's-shared + create/record their own meetings.
    """
    return get_member_role(workspace_id, user_id) == "owner"


def add_workspace_member(
    workspace_id: str,
    user_id: str,
    *,
    role: str = "member",
    added_by: str,
) -> dict:
    """Insert (or promote) a `workspace_members` row. Idempotent on (ws, user).

    Roles are validated against :data:`WORKSPACE_ROLES`. Re-adding an existing
    member updates their role (so an accepted invite can't create a duplicate).
    Returns the resulting `{workspace_id, user_id, role}`.
    """
    if role not in WORKSPACE_ROLES:
        raise ValueError(f"role must be one of {WORKSPACE_ROLES}, got {role!r}")
    conn = _get_conn()
    conn.execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = excluded.role",
        (workspace_id, user_id, role, _now(), added_by),
    )
    return {"workspace_id": workspace_id, "user_id": user_id, "role": role}


def remove_workspace_member(workspace_id: str, user_id: str) -> bool:
    """Remove a member. Returns True if a row was deleted.

    Revocation is pure content-side: the member loses workspace access and any
    meetings shared to them via bare membership. Voiceprint↔scope edges (VFTE #2)
    are a SEPARATE graph and are intentionally untouched (§0.5).
    """
    cur = _get_conn().execute(
        "DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
        (workspace_id, user_id),
    )
    return cur.rowcount > 0


def count_owners(workspace_id: str) -> int:
    """How many owners a workspace has — used to refuse removing the last owner."""
    row = _get_conn().execute(
        "SELECT COUNT(*) AS n FROM workspace_members "
        "WHERE workspace_id = ? AND role = 'owner'",
        (workspace_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def list_workspace_members(workspace_id: str) -> list[dict]:
    """Members of a workspace, owners first then by join time — with their email.

    Joins `users` so the UI can render a real identity, not an opaque id. A member
    with no `users` row yet (shouldn't happen post-signup) still lists with a null
    email rather than being dropped.
    """
    rows = _get_conn().execute(
        "SELECT m.user_id, m.role, m.added_at, u.email, u.display_name "
        "FROM workspace_members m "
        "LEFT JOIN users u ON u.id = m.user_id "
        "WHERE m.workspace_id = ? "
        "ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END, m.added_at ASC",
        (workspace_id,),
    ).fetchall()
    return [dict(r) for r in rows]


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


# --- Workspace invites (Task #32) ------------------------------------------


def _new_invite_id() -> str:
    return f"inv_{secrets.token_hex(4)}"


def create_invite(
    workspace_id: str, email: str, *, role: str = "member", invited_by: str,
) -> dict:
    """Create (or refresh) a pending invite for `email` on this workspace.

    Idempotent per (workspace, email): re-inviting an un-accepted email refreshes
    the token + role rather than piling up rows. Returns
    `{id, workspace_id, email, role, token, created_at}` — the caller emails the
    token as an accept link. `email` is normalised to lowercase (the accept +
    signup-hydration paths match on it).
    """
    if role not in WORKSPACE_ROLES:
        raise ValueError(f"role must be one of {WORKSPACE_ROLES}, got {role!r}")
    if is_personal(workspace_id):
        raise PersonalWorkspaceInviteError(
            f"cannot invite to personal workspace {workspace_id!r} — personal workspaces are solo"
        )
    email = email.strip().lower()
    conn = _get_conn()
    now = _now()
    token = secrets.token_urlsafe(32)
    existing = conn.execute(
        "SELECT id FROM workspace_invites "
        "WHERE workspace_id = ? AND email = ? AND accepted_at IS NULL",
        (workspace_id, email),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE workspace_invites SET token = ?, role = ?, invited_by = ?, "
            "created_at = ? WHERE id = ?",
            (token, role, invited_by, now, existing["id"]),
        )
        invite_id = existing["id"]
    else:
        invite_id = _new_invite_id()
        conn.execute(
            "INSERT INTO workspace_invites "
            "(id, workspace_id, email, role, token, invited_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (invite_id, workspace_id, email, role, token, invited_by, now),
        )
    return {"id": invite_id, "workspace_id": workspace_id, "email": email,
            "role": role, "token": token, "created_at": now}


def get_invite_by_token(token: str) -> Optional[dict]:
    """Resolve a pending (un-accepted) invite by its token, else None."""
    row = _get_conn().execute(
        "SELECT id, workspace_id, email, role, token, invited_by, created_at, "
        "accepted_at, accepted_user_id FROM workspace_invites WHERE token = ?",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def list_pending_invites(workspace_id: str) -> list[dict]:
    """Un-accepted invites for a workspace, newest-first (owner-facing list)."""
    rows = _get_conn().execute(
        "SELECT id, email, role, invited_by, created_at FROM workspace_invites "
        "WHERE workspace_id = ? AND accepted_at IS NULL ORDER BY created_at DESC",
        (workspace_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _accept_invite_row(invite: dict, user_id: str) -> dict:
    """Mark an invite accepted + create the member row. Shared by token + signup."""
    conn = _get_conn()
    conn.execute(
        "UPDATE workspace_invites SET accepted_at = ?, accepted_user_id = ? WHERE id = ?",
        (_now(), user_id, invite["id"]),
    )
    return add_workspace_member(
        invite["workspace_id"], user_id, role=invite["role"], added_by=invite["invited_by"],
    )


def accept_invite(token: str, user_id: str) -> Optional[dict]:
    """Accept an invite by token → `workspace_members` row. Returns the member
    dict, or None if the token is unknown or already accepted. Idempotent-safe:
    an already-accepted token returns None (the member row already exists)."""
    invite = get_invite_by_token(token)
    if invite is None or invite.get("accepted_at"):
        return None
    return _accept_invite_row(invite, user_id)


def accept_pending_invites_for_email(email: str, user_id: str) -> int:
    """Auto-accept every pending invite issued to `email` (called on first sign-in).

    This is the "accept on signup" half of the flow: an owner invites an address
    before that person has an account; when they sign in, their pending invites
    become memberships. Returns how many were accepted. Matches on lowercased email.
    """
    email = email.strip().lower()
    rows = _get_conn().execute(
        "SELECT id, workspace_id, email, role, invited_by, created_at "
        "FROM workspace_invites WHERE email = ? AND accepted_at IS NULL",
        (email,),
    ).fetchall()
    accepted = 0
    for r in rows:
        _accept_invite_row(dict(r), user_id)
        accepted += 1
    return accepted


# --- Whole-workspace meeting share (Task #32) ------------------------------
#
# A one-click "share this meeting with the entire workspace" grant. One row per
# meeting, so it automatically covers members added LATER (unlike snapshotting a
# per-member share). Composes with the per-recipient `meeting_shares` (an email /
# a specific member) instead of overloading the `visibility` enum — that keeps an
# outside-email share and a whole-workspace share able to coexist on one meeting.


def add_meeting_workspace_share(session_id: str, workspace_id: str, granted_by: str) -> None:
    """Grant every member of `workspace_id` access to `session_id` (idempotent)."""
    _get_conn().execute(
        "INSERT INTO meeting_workspace_shares "
        "(session_id, workspace_id, granted_by, granted_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (session_id) DO UPDATE SET "
        "workspace_id = excluded.workspace_id, granted_by = excluded.granted_by, "
        "granted_at = excluded.granted_at",
        (session_id, workspace_id, granted_by, _now()),
    )


def has_meeting_workspace_share(session_id: str) -> bool:
    """True iff this meeting is shared with its whole workspace (Task #32)."""
    row = _get_conn().execute(
        "SELECT 1 FROM meeting_workspace_shares WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return row is not None


def remove_meeting_workspace_share(session_id: str) -> bool:
    """Revoke a whole-workspace share. Returns True if a row was removed."""
    cur = _get_conn().execute(
        "DELETE FROM meeting_workspace_shares WHERE session_id = ?",
        (session_id,),
    )
    return cur.rowcount > 0
