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


def add_meeting_share(session_id: str, user_email: str, granted_by: str) -> None:
    """Grant `user_email` access to a 'shared' meeting. Idempotent (PK absorbs dups)."""
    conn = _get_conn()
    now = _now()
    # Upsert: ignore if already shared, refresh granted_at otherwise.
    conn.execute(
        "INSERT INTO meeting_shares (session_id, user_email, granted_by, granted_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (session_id, user_email) DO UPDATE SET "
        "granted_by = excluded.granted_by, granted_at = excluded.granted_at",
        (session_id, user_email, granted_by, now),
    )


def has_meeting_share(session_id: str, user_email: str) -> bool:
    row = _get_conn().execute(
        "SELECT 1 FROM meeting_shares WHERE session_id = ? AND user_email = ?",
        (session_id, user_email),
    ).fetchone()
    return row is not None


def list_meeting_shares(session_id: str) -> list[dict]:
    rows = _get_conn().execute(
        "SELECT session_id, user_email, granted_by, granted_at, user_id "
        "FROM meeting_shares WHERE session_id = ? ORDER BY granted_at ASC",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]
