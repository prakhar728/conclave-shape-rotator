"""User identity persistence.

Thin sqlite3-based CRUD over the `users` table created in Alembic 0002. Maps
1:1 with Supabase users via `supabase_id`. Style mirrors `storage/sqlite.py`
(typed columns, no ORM).

The auth flow (Phase 1.4) calls `upsert_user_by_supabase` after Supabase
verifies an OTP, so subsequent requests can resolve a cookie → internal
User row without re-hitting Supabase on every call.
"""
from __future__ import annotations

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
