"""User identity persistence.

Thin sqlite3-based CRUD over the `users` table created in Alembic 0002. Maps
1:1 with Supabase users via `supabase_id`. Style mirrors `storage/sqlite.py`
(typed columns, no ORM).

The auth flow (Phase 1.4) calls `upsert_user_by_supabase` after Supabase
verifies an OTP, so subsequent requests can resolve a cookie → internal
User row without re-hitting Supabase on every call.
"""
from __future__ import annotations

import json
import secrets
from typing import Optional

from storage.sqlite import _get_conn, _now


def _new_user_id() -> str:
    return f"usr_{secrets.token_hex(4)}"


def upsert_user_by_supabase(
    supabase_id: str,
    email: str,
    display_name: Optional[str] = None,
) -> dict:
    """Get-or-create a user row keyed by Supabase user id.

    Idempotent — safe to call on every successful OTP verify. Updates email
    and display_name if they changed upstream (e.g. user changed email in
    Supabase). Returns the resolved row as a dict.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, supabase_id, email, display_name, created_at, updated_at "
        "FROM users WHERE supabase_id = ?",
        (supabase_id,),
    ).fetchone()

    now = _now()
    if row is None:
        user_id = _new_user_id()
        conn.execute(
            "INSERT INTO users (id, supabase_id, email, display_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, supabase_id, email, display_name, now, now),
        )
        return {
            "id": user_id,
            "supabase_id": supabase_id,
            "email": email,
            "display_name": display_name,
            "created_at": now,
            "updated_at": now,
        }

    # Existing user — patch email/display_name if drifted.
    if row["email"] != email or row["display_name"] != display_name:
        conn.execute(
            "UPDATE users SET email = ?, display_name = ?, updated_at = ? WHERE id = ?",
            (email, display_name, now, row["id"]),
        )
        return {
            "id": row["id"],
            "supabase_id": row["supabase_id"],
            "email": email,
            "display_name": display_name,
            "created_at": row["created_at"],
            "updated_at": now,
        }
    return dict(row)


def get_user(user_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, supabase_id, email, display_name, created_at, updated_at "
        "FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, supabase_id, email, display_name, created_at, updated_at "
        "FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    return dict(row) if row else None


def get_user_by_supabase(supabase_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, supabase_id, email, display_name, created_at, updated_at "
        "FROM users WHERE supabase_id = ?",
        (supabase_id,),
    ).fetchone()
    return dict(row) if row else None


# --- Account settings (users.settings JSON, Alembic 0012) ------------------

def get_user_settings(user_id: str) -> dict:
    """Return the user's settings dict (empty `{}` if unset or row missing).

    Settings live in a JSON blob so new preferences don't each need a
    migration. Today the only key is `retention_days` (null/absent = keep
    transcripts forever).
    """
    row = _get_conn().execute(
        "SELECT settings FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None or row["settings"] is None:
        return {}
    try:
        return json.loads(row["settings"]) or {}
    except (ValueError, TypeError):
        return {}


def set_user_settings(user_id: str, settings: dict) -> dict:
    """Replace the user's settings blob. Returns the stored dict."""
    _get_conn().execute(
        "UPDATE users SET settings = ?, updated_at = ? WHERE id = ?",
        (json.dumps(settings), _now(), user_id),
    )
    return settings


def get_account_retention_days(user_id: str) -> Optional[int]:
    """Account-wide default retention in days, or None for keep-forever.

    Resilient to junk: a non-positive or non-int value reads as keep-forever.
    """
    val = get_user_settings(user_id).get("retention_days")
    if isinstance(val, bool):  # bool is an int subclass — reject explicitly
        return None
    if isinstance(val, int) and val > 0:
        return val
    return None


def get_auto_record_all_workspace(user_id: str) -> Optional[str]:
    """Workspace id for the account-wide "record all my meetings" option, or
    None when it's off.

    When set, the poller auto-records every upcoming Google Meet the user
    hasn't explicitly opted out of, dropping each transcript in this workspace.
    """
    val = get_user_settings(user_id).get("auto_record_all_workspace_id")
    return val if isinstance(val, str) and val else None


def set_auto_record_all(user_id: str, workspace_id: Optional[str]) -> None:
    """Enable (pass a workspace_id) or disable (pass None) account-wide
    auto-record. Merges into the existing settings blob."""
    s = get_user_settings(user_id)
    if workspace_id:
        s["auto_record_all_workspace_id"] = workspace_id
    else:
        s.pop("auto_record_all_workspace_id", None)
    set_user_settings(user_id, s)
