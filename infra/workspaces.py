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


# --- Meeting shares (Phase 1.7 / 2.x consumer) ---


#: Permission levels a share can grant. 'summary_and_transcript' is the default
#: (and what every pre-0011 row back-fills to); 'summary_only' withholds the raw
#: transcript at the gated /transcripts/sessions/{id}/transcript endpoint.
SHARE_SCOPES = ("summary_and_transcript", "summary_only")
_DEFAULT_SHARE_SCOPE = "summary_and_transcript"


def add_meeting_share(
    session_id: str,
    user_email: str,
    granted_by: str,
    scope: str = _DEFAULT_SHARE_SCOPE,
) -> None:
    """Grant `user_email` access to a 'shared' meeting at permission `scope`.

    Idempotent (PK absorbs dups); re-sharing the same email updates the scope,
    so an owner can downgrade summary+transcript → summary-only (or back) by
    re-adding the same recipient.
    """
    if scope not in SHARE_SCOPES:
        raise ValueError(f"scope must be one of {SHARE_SCOPES}, got {scope!r}")
    conn = _get_conn()
    now = _now()
    # Upsert: ignore if already shared, refresh granted_at + scope otherwise.
    conn.execute(
        "INSERT INTO meeting_shares (session_id, user_email, granted_by, granted_at, scope) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (session_id, user_email) DO UPDATE SET "
        "granted_by = excluded.granted_by, granted_at = excluded.granted_at, "
        "scope = excluded.scope",
        (session_id, user_email, granted_by, now, scope),
    )


def has_meeting_share(session_id: str, user_email: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM meeting_shares WHERE session_id = ? AND user_email = ?",
        (session_id, user_email),
    ).fetchone()
    return row is not None


def get_meeting_share_scope(session_id: str, user_email: str) -> Optional[str]:
    """Return the share scope granted to `user_email`, or None if not shared.

    Used by the transcript gate to decide whether a 'shared' recipient is
    allowed the raw transcript ('summary_and_transcript') or only the derived
    summary ('summary_only').
    """
    row = _get_conn().execute(
        "SELECT scope FROM meeting_shares WHERE session_id = ? AND user_email = ?",
        (session_id, user_email),
    ).fetchone()
    return row["scope"] if row else None


def list_meeting_shares(session_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT session_id, user_email, granted_by, granted_at, user_id, scope "
        "FROM meeting_shares WHERE session_id = ? ORDER BY granted_at ASC",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]
